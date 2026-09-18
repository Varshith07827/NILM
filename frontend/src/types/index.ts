/**
 * Wire types.
 *
 * These mirror the frames produced by `NILMPipeline._build_frame` on the
 * backend. The backend deliberately does not re-validate the live frame
 * through Pydantic on every window (it would add latency to a hot path to
 * re-check data the process just built), so these interfaces are the contract
 * that pins its shape on the consumer side.
 */

export interface Measurement {
  current_a: number;
  voltage_v: number;
  power_w: number;
  reactive_var: number;
  apparent_va: number;
  power_factor: number;
  thd: number;
  peak_current_a: number;
  crest_factor: number;
  frequency_hz: number;
}

export interface EnergyBlock {
  window_wh: number;
  today_wh: number;
  month_wh: number;
  session_wh: number;
  peak_power_w: number;
  peak_power_today_w: number;
  average_power_w: number;
  load_factor: number;
  elapsed_sim_s: number;
  sanctioned_load_w: number;
}

export interface CostBlock {
  today_inr: number;
  month_inr: number;
  session_inr: number;
  projected_month_inr: number;
  monthly_bill_inr: number;
  marginal_rate_inr: number;
  effective_rate_inr: number;
  tariff_name: string;
  currency_symbol: string;
}

export interface ApplianceFrame {
  id: string;
  name: string;
  icon: string;
  category: string;
  colour: string;
  rated_power_w: number;
  probability: number;
  threshold: number;
  detected: boolean;
  estimated_power_w: number;
  /** Ground truth from the simulator. The model never sees this. */
  actual_power_w: number;
  actually_on: boolean;
  socket_on: boolean;
  energy_wh_today: number;
  cost_today_inr: number;
  runtime_s_today: number;
}

export type EventAction = "on" | "off";
export type EventSource =
  | "script"
  | "autonomous"
  | "manual"
  | "scenario"
  | "replay";

export interface ApplianceEvent {
  timestamp: string;
  appliance_id: string;
  appliance_name: string;
  action: EventAction;
  source: EventSource;
  note: string;
  power_w: number;
}

export type AlertLevel = "info" | "success" | "warning" | "critical";

export interface Alert {
  sim_time: string;
  level: AlertLevel;
  category: string;
  title: string;
  message: string;
  value: number;
}

export interface InferenceBlock {
  backend: string;
  latency_ms: number;
  /** Median over a rolling window — see the note in PipelineStats. */
  median_latency_ms: number;
  p95_latency_ms: number;
}

export interface AccuracyBlock {
  precision: number;
  recall: number;
  f1: number;
  window: number;
  avg_detection_latency_s: number | null;
}

export interface ScopeBlock {
  sample_rate_hz: number;
  current: number[];
  voltage: number[];
}

export type SimulationState = "stopped" | "running" | "paused";
export type SimulationMode = "demo" | "simulation" | "replay";

export interface LiveFrame {
  sim_time: string;
  sim_seconds: number;
  wall_time: string;
  state: SimulationState;
  mode: SimulationMode;
  scenario: string;
  speed: number;
  run_id: string;
  measurement: Measurement;
  energy: EnergyBlock;
  cost: CostBlock;
  appliances: ApplianceFrame[];
  detected: string[];
  unattributed_w: number;
  residual_a: number;
  inference: InferenceBlock;
  accuracy: AccuracyBlock;
  events: ApplianceEvent[];
  alerts: Alert[];
  scope: ScopeBlock;
}

export interface TariffSlab {
  up_to_kwh: number | null;
  rate_inr: number;
}

export interface Tariff {
  id: string;
  name: string;
  description: string;
  fixed_charge_inr: number;
  currency: string;
  currency_symbol: string;
  slabs: TariffSlab[];
}

export interface ModelInfo {
  backend: string;
  model_available: boolean;
  architecture: string;
  parameters: number;
  sequence_length: number;
  num_features: number;
  metrics: {
    macro_f1?: number;
    micro_f1?: number;
    hamming_accuracy?: number;
    exact_match_accuracy?: number;
    training_seconds?: number;
    training_windows?: number;
    epochs_run?: number;
  };
  load_error: string | null;
  artifact_dir: string;
  thresholds?: Record<string, number>;
}

export interface ScenarioInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  start_hour: number;
  activity: number;
  always_on: string[];
  never_on: string[];
  scripted_events: number;
  script_duration_s: number;
}

export interface RecordingSummary {
  name: string;
  file: string;
  scenario_id: string;
  mode: string;
  seed: number;
  created_at: string;
  frame_count: number;
  duration_s: number;
  start_sim_time: string;
}

export interface SimulationStatus {
  state: SimulationState;
  mode: SimulationMode;
  speed: number;
  seed: number;
  run_id: string;
  scenario: {
    id: string;
    name: string;
    description: string;
    icon: string;
    start_hour: number;
  };
  sim_time: string;
  recording: {
    active: boolean;
    frames: number;
    name: string | null;
    replay_progress: number | null;
  };
  tariff: Tariff;
  model: ModelInfo;
  stats: {
    windows_processed: number;
    rows_written: number;
    inference_ms_median: number;
    inference_ms_p95: number;
    loop_ms_median: number;
    behind_realtime: boolean;
    buffered_rows: number;
    subscribers: number;
  };
}

export interface ApplianceSpec {
  id: string;
  name: string;
  icon: string;
  category: string;
  colour: string;
  load_type: string;
  rated_power_w: number;
  power_factor: number;
  rms_current_a: number;
  displacement_power_factor: number;
  distortion_power_factor: number;
  phase_angle_deg: number;
  thd_percent: number;
  peak_startup_current_a: number;
  startup_multiplier: number;
  standby_w: number;
  has_duty_cycle: boolean;
  duty_ratio: number | null;
  harmonics: Record<string, number>;
}

export interface ReportApplianceRow {
  appliance_id: string;
  name: string;
  colour: string;
  energy_wh: number;
  energy_kwh: number;
  cost_inr: number;
  runtime_s: number;
  peak_power_w: number;
  share: number;
}

export interface Report {
  period: string;
  generated_at: string;
  start: string | null;
  end: string | null;
  run_id: string;
  total_energy_kwh: number;
  total_cost_inr: number;
  peak_power_w: number;
  average_power_w: number;
  appliances: ReportApplianceRow[];
  hourly: { bucket_start: string; energy_wh: number; cost_inr: number }[];
  daily: {
    day: string;
    energy_wh: number;
    energy_kwh: number;
    cost_inr: number;
  }[];
  tariff: Tariff;
  slab_breakdown: SlabRow[];
}

export interface SlabRow {
  from_kwh: number;
  to_kwh: number | null;
  rate_inr: number;
  units: number;
  charge_inr: number;
  active: boolean;
}

export interface CostResponse {
  today_inr: number;
  month_inr: number;
  session_inr: number;
  projected_month_inr: number;
  monthly_bill_inr: number;
  marginal_rate_inr: number;
  effective_rate_inr: number;
  energy_today_kwh: number;
  energy_month_kwh: number;
  per_appliance: {
    appliance_id: string;
    cost_today_inr: number;
    cost_month_inr: number;
    energy_today_wh: number;
    energy_month_wh: number;
    runtime_s_today: number;
  }[];
  slab_breakdown: SlabRow[];
  tariff: Tariff;
}

/** Messages pushed over the WebSocket. */
export type SocketMessage =
  | { type: "frame"; data: LiveFrame }
  | { type: "status"; data: SimulationStatus }
  | {
      type: "snapshot";
      data: { frames: LiveFrame[]; alerts: Alert[]; events: ApplianceEvent[] };
    }
  | { type: "pong" };
