import { Check, Power, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { InfoTip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { applianceIcon } from "@/lib/icons";
import { cn, formatDuration, formatPower, percent } from "@/lib/utils";
import type { ApplianceFrame } from "@/types";

/** Resolve the lucide icon named by the backend, with a sane fallback. */
function ApplianceIcon({ name, className }: { name: string; className?: string }) {
  const Icon = applianceIcon(name);
  return <Icon className={className} />;
}

interface Props {
  appliances: ApplianceFrame[];
  /** Show the simulator ground truth beside the prediction. */
  showTruth: boolean;
  onToggleTruth: (value: boolean) => void;
  onChanged: () => void;
}

export function ApplianceGrid({
  appliances,
  showTruth,
  onToggleTruth,
  onChanged,
}: Props) {
  const [pending, setPending] = useState<string | null>(null);

  const detectedCount = appliances.filter((a) => a.detected).length;
  const actualCount = appliances.filter((a) => a.actually_on).length;

  const toggle = async (appliance: ApplianceFrame) => {
    setPending(appliance.id);
    try {
      await api.toggleAppliance(appliance.id, !appliance.socket_on);
      onChanged();
    } finally {
      setPending(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="space-y-1">
          <CardTitle>
            <Power className="h-3.5 w-3.5 text-primary" />
            Appliance Detection
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            {detectedCount} detected
            {showTruth ? (
              <span className="text-muted-foreground/70">
                {" "}
                · {actualCount} actually running
              </span>
            ) : null}
          </p>
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-[0.7rem] text-muted-foreground">
          <InfoTip label="Reveal the simulator's hidden ground truth beside each prediction. The model never sees these values — this is purely for scoring the demonstration.">
            <span className="cursor-help">Ground truth</span>
          </InfoTip>
          <Switch checked={showTruth} onCheckedChange={onToggleTruth} />
        </label>
      </CardHeader>

      <CardContent>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {appliances.map((appliance) => {
            const confidence = appliance.probability;
            const correct = appliance.detected === appliance.actually_on;
            const share = appliance.rated_power_w
              ? Math.min(
                  1,
                  appliance.estimated_power_w / appliance.rated_power_w,
                )
              : 0;

            return (
              <div
                key={appliance.id}
                className={cn(
                  "group relative overflow-hidden rounded-lg border p-3 transition-all duration-200",
                  appliance.detected
                    ? "border-white/[0.09] bg-secondary/40"
                    : "border-border/40 bg-transparent opacity-70 hover:opacity-100",
                )}
              >
                {/* colour wash for a detected appliance */}
                {appliance.detected ? (
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0 opacity-[0.09]"
                    style={{
                      background: `radial-gradient(24rem 8rem at 0% 0%, ${appliance.colour}, transparent 70%)`,
                    }}
                  />
                ) : null}

                <div className="relative flex items-start gap-2.5">
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors"
                    style={{
                      background: appliance.detected
                        ? `${appliance.colour}24`
                        : "hsl(var(--secondary))",
                      color: appliance.detected
                        ? appliance.colour
                        : "hsl(var(--muted-foreground))",
                    }}
                  >
                    <ApplianceIcon
                      name={appliance.icon}
                      className="h-4 w-4"
                    />
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <Link
                        to={`/appliances/${encodeURIComponent(appliance.id)}`}
                        className="truncate text-xs font-semibold hover:text-primary hover:underline"
                      >
                        {appliance.name}
                      </Link>
                      {showTruth ? (
                        <InfoTip
                          label={
                            correct
                              ? "The detector agrees with the simulator"
                              : appliance.detected
                                ? "False positive: detected but not actually running"
                                : "Missed: running but not detected"
                          }
                        >
                          <span
                            className={cn(
                              "flex h-3.5 w-3.5 shrink-0 cursor-help items-center justify-center rounded-full",
                              correct
                                ? "bg-success/20 text-success"
                                : "bg-destructive/20 text-destructive",
                            )}
                          >
                            {correct ? (
                              <Check className="h-2.5 w-2.5" />
                            ) : (
                              <X className="h-2.5 w-2.5" />
                            )}
                          </span>
                        </InfoTip>
                      ) : null}
                    </div>

                    <p className="truncate text-[0.62rem] text-muted-foreground">
                      {appliance.room_name} · {appliance.rated_power_w} W rated
                    </p>
                    <div className="mt-0.5 flex items-baseline gap-1">
                      <span className="font-mono text-base font-semibold tabular-nums">
                        {formatPower(appliance.estimated_power_w).value}
                      </span>
                      <span className="text-[0.65rem] text-muted-foreground">
                        {formatPower(appliance.estimated_power_w).unit}
                      </span>
                      {showTruth ? (
                        <span className="ml-auto font-mono text-[0.65rem] text-muted-foreground">
                          true {appliance.actual_power_w.toFixed(0)} W
                        </span>
                      ) : null}
                    </div>
                  </div>

                  <InfoTip
                    label={`Switch ${appliance.name} ${
                      appliance.socket_on ? "off" : "on"
                    } at the socket`}
                  >
                    <button
                      type="button"
                      disabled={pending === appliance.id}
                      onClick={() => void toggle(appliance)}
                      className={cn(
                        "flex h-6 w-6 shrink-0 items-center justify-center rounded-md border transition-colors",
                        appliance.socket_on
                          ? "border-success/30 bg-success/15 text-success"
                          : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
                        pending === appliance.id && "opacity-50",
                      )}
                      aria-label={`Toggle ${appliance.name}`}
                    >
                      <Power className="h-3 w-3" />
                    </button>
                  </InfoTip>
                </div>

                {/* confidence rail */}
                <div className="relative mt-2.5 space-y-1">
                  <div className="flex items-center justify-between text-[0.62rem] text-muted-foreground">
                    <span>confidence</span>
                    <span className="font-mono tabular-nums">
                      {percent(confidence, 0)}
                    </span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-secondary/70">
                    <div
                      className="h-full rounded-full transition-[width] duration-300 ease-out"
                      style={{
                        width: `${Math.max(2, confidence * 100)}%`,
                        background: appliance.detected
                          ? appliance.colour
                          : "hsl(var(--muted-foreground) / 0.4)",
                      }}
                    />
                  </div>
                  {/* decision threshold marker */}
                  <div
                    aria-hidden
                    className="pointer-events-none absolute bottom-0 h-1 w-px bg-foreground/40"
                    style={{ left: `${appliance.threshold * 100}%` }}
                  />
                </div>

                <div className="mt-2 flex items-center justify-between text-[0.62rem] text-muted-foreground">
                  <span>
                    {appliance.energy_wh_today < 1000
                      ? `${appliance.energy_wh_today.toFixed(1)} Wh today`
                      : `${(appliance.energy_wh_today / 1000).toFixed(2)} kWh today`}
                  </span>
                  <span>{formatDuration(appliance.runtime_s_today)}</span>
                </div>

                {share > 0 ? (
                  <div
                    aria-hidden
                    className="absolute inset-x-0 bottom-0 h-[2px]"
                    style={{
                      width: `${share * 100}%`,
                      background: appliance.colour,
                      opacity: 0.55,
                    }}
                  />
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-[0.65rem] text-muted-foreground">
          <Badge variant="outline">
            <span className="h-1.5 w-1.5 rounded-full bg-foreground/40" />
            tick marks the decision threshold
          </Badge>
          <span>
            Thresholds are tuned per appliance on the validation split, not
            fixed at 0.5.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
