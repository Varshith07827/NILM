import {
  ArrowUpRight,
  Box,
  Eye,
  EyeOff,
  Home,
  Loader2,
  MousePointerClick,
  Power,
  RotateCcw,
} from "lucide-react";
import { Suspense, lazy, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { InfoTip } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  CAMERA_PRESET_NAMES,
  cameraPosition,
  layoutHouse,
  type CameraPreset,
} from "@/components/house/layout";
import { api } from "@/lib/api";
import { applianceIcon } from "@/lib/icons";
import {
  cn,
  formatCurrency,
  formatDuration,
  formatEnergy,
  formatPower,
  percent,
} from "@/lib/utils";
import { useLive } from "@/state/live";
import type { ApplianceFrame } from "@/types";

/**
 * Three.js is by far the heaviest dependency in the bundle, and it is only
 * needed on this one page. Lazy-loading it keeps the initial load of every
 * other page fast.
 */
const HouseScene = lazy(() =>
  import("@/components/house/HouseScene").then((module) => ({
    default: module.HouseScene,
  })),
);

const PRESET_LABELS: Record<CameraPreset, string> = {
  isometric: "Isometric",
  front: "Front",
  top: "Top-down",
};

export default function HomeView() {
  const { frame, showTruth, setShowTruth, onChanged } = useLive();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [preset, setPreset] = useState<CameraPreset>("isometric");
  const [busy, setBusy] = useState<string | null>(null);

  const appliances = frame?.appliances ?? [];
  const rooms = frame?.rooms ?? [];

  // Laid out again only when the house itself changes, not on every frame.
  const layoutKey = JSON.stringify([
    rooms,
    appliances.map((a) => [a.id, a.type_id, a.room_id]),
  ]);
  const layout = useMemo(
    () => layoutHouse(rooms, appliances),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layoutKey],
  );

  /** Fractional hour of the simulated day, which drives the scene lighting. */
  const hour = useMemo(() => {
    if (!frame) return 18;
    const date = new Date(frame.sim_time);
    return date.getHours() + date.getMinutes() / 60;
  }, [frame?.sim_time]);

  const selected = appliances.find((a) => a.id === selectedId) ?? null;

  const roomTotals = useMemo(() => {
    const totals = layout.rooms.map((room) => ({
      ...room,
      watts: 0,
      running: 0,
      appliances: [] as ApplianceFrame[],
    }));
    const index = Object.fromEntries(totals.map((room) => [room.id, room]));
    for (const appliance of appliances) {
      const room = index[appliance.room_id];
      if (!room) continue;
      room.appliances.push(appliance);
      if (appliance.detected) {
        room.watts += appliance.estimated_power_w;
        room.running += 1;
      }
    }
    return totals.sort((a, b) => b.watts - a.watts);
  }, [appliances, layout.rooms]);

  const toggle = async (appliance: ApplianceFrame) => {
    setBusy(appliance.id);
    try {
      await api.toggleAppliance(appliance.id, !appliance.socket_on);
      onChanged();
    } catch {
      /* the control panel surfaces failures; the scene stays responsive */
    } finally {
      setBusy(null);
    }
  };

  const detectedCount = appliances.filter((a) => a.detected).length;
  const actualCount = appliances.filter((a) => a.actually_on).length;
  const mismatches = appliances.filter(
    (a) => a.detected !== a.actually_on,
  ).length;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Home}
        title="3D Home"
        description="The simulated household. Click any device to see its usage and cost; switch it from the inspector, and the detector has to work out what you did from the mains current alone."
        actions={
          <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-border/60 bg-secondary/40 px-3 py-1.5 text-[0.7rem] text-muted-foreground">
            {showTruth ? (
              <Eye className="h-3.5 w-3.5" />
            ) : (
              <EyeOff className="h-3.5 w-3.5" />
            )}
            Ground truth
            <Switch checked={showTruth} onCheckedChange={setShowTruth} />
          </label>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* ------------------------------------------------------------ */}
        {/* the scene                                                     */}
        {/* ------------------------------------------------------------ */}
        <Card className="relative overflow-hidden xl:col-span-8">
          <div className="absolute left-4 top-4 z-10 flex flex-wrap items-center gap-1.5">
            {CAMERA_PRESET_NAMES.map((name) => (
              <Button
                key={name}
                size="sm"
                variant={preset === name ? "default" : "outline"}
                className="h-7 px-2.5 text-[0.68rem] backdrop-blur-md"
                onClick={() => setPreset(name)}
              >
                {PRESET_LABELS[name]}
              </Button>
            ))}
          </div>

          <div className="absolute right-4 top-4 z-10 flex flex-col items-end gap-1.5">
            <Badge variant="secondary" className="backdrop-blur-md">
              {detectedCount} running
            </Badge>
            {showTruth && mismatches > 0 ? (
              <InfoTip label="Appliances where the detector and the simulator currently disagree. Rings on the floor mark them.">
                <Badge variant="warning" className="cursor-help backdrop-blur-md">
                  {mismatches} mismatch{mismatches === 1 ? "" : "es"}
                </Badge>
              </InfoTip>
            ) : null}
            {showTruth && mismatches === 0 && actualCount > 0 ? (
              <Badge variant="success" className="backdrop-blur-md">
                all correct
              </Badge>
            ) : null}
          </div>

          <div className="absolute bottom-3 left-4 z-10 flex items-center gap-1.5 rounded-md border border-border/50 bg-background/70 px-2 py-1 text-[0.64rem] text-muted-foreground backdrop-blur-md">
            <MousePointerClick className="h-3 w-3" />
            Click a device to inspect · drag to orbit · scroll to zoom
          </div>

          <div className="h-[420px] w-full sm:h-[560px] xl:h-[640px]">
            <Suspense
              fallback={
                <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <p className="text-xs">Loading the house…</p>
                </div>
              }
            >
              {frame ? (
                <HouseScene
                  appliances={appliances}
                  layout={layout}
                  hour={hour}
                  showTruth={showTruth}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  cameraPosition={cameraPosition(preset, layout)}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                  Waiting for the first acquisition window…
                </div>
              )}
            </Suspense>
          </div>
        </Card>

        {/* ------------------------------------------------------------ */}
        {/* side panel                                                    */}
        {/* ------------------------------------------------------------ */}
        <div className="space-y-4 xl:col-span-4">
          {/* --- selected appliance --- */}
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
              <CardTitle>
                <Box className="h-3.5 w-3.5 text-primary" />
                {selected ? selected.name : "Inspector"}
              </CardTitle>
              {selected ? (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => setSelectedId(null)}
                  aria-label="Clear selection"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              ) : null}
            </CardHeader>
            <CardContent>
              {selected ? (
                <ApplianceInspector
                  appliance={selected}
                  showTruth={showTruth}
                  busy={busy === selected.id}
                  onToggle={() => void toggle(selected)}
                  currencySymbol={frame?.cost.currency_symbol ?? "₹"}
                />
              ) : (
                <p className="py-6 text-center text-xs text-muted-foreground">
                  Select a device in the house to see its usage and cost.
                </p>
              )}
            </CardContent>
          </Card>

          {/* --- room breakdown --- */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>
                <Home className="h-3.5 w-3.5 text-primary" />
                Load by Room
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {roomTotals.map((room) => {
                const share = frame?.measurement.power_w
                  ? room.watts / frame.measurement.power_w
                  : 0;
                const formatted = formatPower(room.watts);
                return (
                  <div key={room.id} className="space-y-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[0.72rem] font-medium">{room.name}</span>
                      <span className="text-[0.64rem] text-muted-foreground">
                        {room.running}/{room.appliances.length} on
                      </span>
                      <span className="ml-auto font-mono text-xs font-semibold tabular-nums">
                        {formatted.value}
                        <span className="ml-0.5 text-[0.62rem] font-normal text-muted-foreground">
                          {formatted.unit}
                        </span>
                      </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary/70">
                      <div
                        className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
                        style={{ width: `${Math.min(100, share * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {/* --- legend --- */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Legend</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-[0.7rem] text-muted-foreground">
              <LegendRow colour="#22d3ee" label="Detected and drawing power" />
              <LegendRow colour="#2a3547" label="Off, or below standby threshold" />
              {showTruth ? (
                <>
                  <LegendRow
                    colour="#ef4444"
                    label="Missed — running, but the model did not detect it"
                  />
                  <LegendRow
                    colour="#f59e0b"
                    label="False positive — detected, but not actually running"
                  />
                </>
              ) : null}
              <Separator className="my-2" />
              <p className="leading-relaxed">
                Scene lighting follows the simulated clock. Switch to the{" "}
                <span className="font-medium text-foreground">Night</span>{" "}
                scenario and the house goes dark — the only light left comes from
                appliances genuinely drawing power.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function LegendRow({ colour, label }: { colour: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ background: colour }}
      />
      <span>{label}</span>
    </div>
  );
}

function ApplianceInspector({
  appliance,
  showTruth,
  busy,
  onToggle,
  currencySymbol,
}: {
  appliance: ApplianceFrame;
  showTruth: boolean;
  busy: boolean;
  onToggle: () => void;
  currencySymbol: string;
}) {
  const Icon = applianceIcon(appliance.icon);
  const estimated = formatPower(appliance.estimated_power_w);
  const correct = appliance.detected === appliance.actually_on;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
          style={{
            background: appliance.detected
              ? `${appliance.colour}24`
              : "hsl(var(--secondary))",
            color: appliance.detected
              ? appliance.colour
              : "hsl(var(--muted-foreground))",
          }}
        >
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[0.68rem] text-muted-foreground">
            {appliance.room_name} · rated {appliance.rated_power_w} W
          </p>
          <div className="flex items-baseline gap-1">
            <span className="font-mono text-xl font-bold tabular-nums">
              {estimated.value}
            </span>
            <span className="text-[0.7rem] text-muted-foreground">
              {estimated.unit}
            </span>
          </div>
        </div>
        <Button
          size="sm"
          variant={appliance.socket_on ? "destructive" : "success"}
          disabled={busy}
          onClick={onToggle}
        >
          <Power className="h-3.5 w-3.5" />
          {appliance.socket_on ? "Off" : "On"}
        </Button>
      </div>

      {/* confidence */}
      <div className="space-y-1">
        <div className="flex items-baseline justify-between text-[0.66rem]">
          <span className="text-muted-foreground">
            {appliance.type_name} confidence
          </span>
          <span className="font-mono tabular-nums">
            {percent(appliance.probability, 0)}
          </span>
        </div>
        <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-secondary/70">
          <div
            className="h-full rounded-full transition-[width] duration-300"
            style={{
              width: `${Math.max(2, appliance.probability * 100)}%`,
              background: appliance.detected
                ? appliance.colour
                : "hsl(var(--muted-foreground) / 0.4)",
            }}
          />
          <div
            aria-hidden
            className="absolute inset-y-0 w-px bg-foreground/50"
            style={{ left: `${appliance.threshold * 100}%` }}
          />
        </div>
        <p className="text-[0.62rem] text-muted-foreground">
          Decision threshold {appliance.threshold.toFixed(2)}. The classifier
          recognises appliance <em>types</em>; which{" "}
          {appliance.type_name.toLowerCase()} is running is worked out from its
          switching signature.
        </p>
      </div>

      <Separator />

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[0.68rem]">
        <Field
          label="Current"
          value={`${appliance.estimated_current_a.toFixed(3)} A`}
        />
        <Field label="Socket" value={appliance.socket_on ? "on" : "off"} />
        <Field label="Energy today" value={energyLabel(appliance.energy_wh_today)} />
        <Field label="Runtime today" value={formatDuration(appliance.runtime_s_today)} />
        <Field
          label="Cost today"
          value={formatCurrency(appliance.cost_today_inr, currencySymbol)}
        />
        <Field
          label="Cost this month"
          value={formatCurrency(appliance.cost_month_inr, currencySymbol)}
        />
        {showTruth ? (
          <>
            <Field
              label="Actual draw"
              value={`${appliance.actual_power_w.toFixed(1)} W`}
            />
            <Field
              label="Verdict"
              value={correct ? "correct" : appliance.detected ? "false positive" : "missed"}
              tone={correct ? "success" : "destructive"}
            />
          </>
        ) : null}
      </dl>

      <Button asChild variant="outline" size="sm" className="w-full">
        <Link to={`/appliances/${encodeURIComponent(appliance.id)}`}>
          Usage history and cost
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </Button>
    </div>
  );
}

function energyLabel(wh: number) {
  const formatted = formatEnergy(wh);
  return `${formatted.value} ${formatted.unit}`;
}

function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "success" | "destructive";
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "font-mono font-medium tabular-nums",
          tone === "success" && "text-success",
          tone === "destructive" && "text-destructive",
        )}
      >
        {value}
      </dd>
    </div>
  );
}
