/**
 * Typed REST client.
 *
 * All requests go through `/api`, which Vite proxies to the FastAPI backend in
 * development. In a production build the dashboard is served from the same
 * origin as the API, so the relative path keeps working unchanged.
 */

import type {
  ApplianceSpec,
  CostResponse,
  LiveFrame,
  ModelInfo,
  RecordingSummary,
  Report,
  ScenarioInfo,
  SimulationStatus,
  Tariff,
} from "@/types";

const BASE = "/api";

export class ApiError extends Error {
  // Declared as a field rather than a constructor parameter property, because
  // `erasableSyntaxOnly` forbids syntax that emits runtime code.
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* the body was not JSON; the status text will have to do */
    }
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    );
  }

  return (await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

interface MessageResponse {
  ok: boolean;
  message: string;
  detail?: unknown;
}

export const api = {
  // --- live ------------------------------------------------------------ #
  status: () => request<SimulationStatus>("/status"),
  live: () =>
    request<{ available: boolean; frame?: LiveFrame }>("/live"),
  appliances: () => request<ApplianceSpec[]>("/appliances"),
  scenarios: () => request<ScenarioInfo[]>("/scenarios"),
  model: () => request<ModelInfo>("/model"),
  signatures: () =>
    request<{ orders: number[]; appliances: unknown[] }>("/model/signatures"),

  // --- simulation controls --------------------------------------------- #
  start: () => post<MessageResponse>("/simulation/start"),
  pause: () => post<MessageResponse>("/simulation/pause"),
  resume: () => post<MessageResponse>("/simulation/resume"),
  stop: () => post<MessageResponse>("/simulation/stop"),
  reset: (body: {
    scenario_id?: string;
    mode?: string;
    seed?: number;
    clear_history?: boolean;
  }) => post<MessageResponse>("/simulation/reset", body),
  setSpeed: (speed: number) =>
    post<MessageResponse>("/simulation/speed", { speed }),
  setScenario: (scenario_id: string) =>
    post<MessageResponse>("/simulation/scenario", { scenario_id }),
  setMode: (mode: string, recording_file?: string) =>
    post<MessageResponse>("/simulation/mode", { mode, recording_file }),
  toggleAppliance: (appliance_id: string, on: boolean) =>
    post<MessageResponse>("/simulation/appliance", { appliance_id, on }),

  // --- recordings -------------------------------------------------------- #
  recordings: () =>
    request<{ recordings: RecordingSummary[] }>("/simulation/recordings"),
  startRecording: (name: string) =>
    post<MessageResponse>("/simulation/recordings/start", { name }),
  stopRecording: () => post<MessageResponse>("/simulation/recordings/stop"),

  // --- cost --------------------------------------------------------------- #
  cost: () => request<CostResponse>("/cost"),
  tariffs: () => request<Tariff[]>("/tariffs"),
  setTariff: (body: {
    tariff_id?: string;
    name?: string;
    fixed_charge_inr?: number;
    slabs?: { up_to_kwh: number | null; rate_inr: number }[];
  }) => post<MessageResponse>("/settings/tariff", body),
  setAlerts: (body: {
    high_power_threshold_w?: number;
    daily_cost_alert_inr?: number;
    peak_current_alert_a?: number;
    sanctioned_load_w?: number;
  }) => post<MessageResponse>("/settings/alerts", body),
  settings: () => request<Record<string, unknown>>("/settings"),

  // --- reports ------------------------------------------------------------ #
  report: (period: "daily" | "weekly" | "monthly") =>
    request<Report>(`/reports?period=${period}`),

  /** URL for a CSV/PDF download; used directly as an anchor href. */
  reportDownloadUrl: (
    period: "daily" | "weekly" | "monthly",
    format: "csv" | "pdf",
  ) => `${BASE}/reports?period=${period}&format=${format}`,

  // --- history ------------------------------------------------------------ #
  history: (maxPoints = 1500) =>
    request<{
      run_id: string;
      total_rows: number;
      decimated: boolean;
      points: {
        sim_time: string;
        current_a: number;
        voltage_v: number;
        power_w: number;
        power_factor: number;
        thd: number;
        energy_wh: number;
        cost_inr: number;
        detected: string[];
      }[];
    }>(`/history?max_points=${maxPoints}`),
};
