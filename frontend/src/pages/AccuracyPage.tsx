import { Cpu, ListChecks } from "lucide-react";

import { AccuracyPanel } from "@/components/AccuracyPanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { applianceIcon } from "@/lib/icons";
import { cn, percent } from "@/lib/utils";
import { useLive } from "@/state/live";

export default function AccuracyPage() {
  const { frame, status, showTruth } = useLive();
  const types = frame?.types ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Cpu}
        title="Model Accuracy"
        description="How well the classifier is doing right now against the simulator's hidden truth, and what it is running on."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AccuracyPanel frame={frame} model={status?.model ?? null} />

        <Card>
          <CardHeader className="pb-3">
            <CardTitle>
              <ListChecks className="h-3.5 w-3.5 text-primary" />
              Classifier output by type
            </CardTitle>
            <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
              The model recognises appliance types, not individual devices. With
              several devices of a type in the house, it says whether{" "}
              <em>any</em> is running; which one is worked out afterwards from
              switching signatures.
            </p>
          </CardHeader>
          <CardContent className="space-y-2">
            {types.map((type) => {
              const Icon = applianceIcon(type.icon);
              const correct = type.detected === type.actually_on;
              return (
                <div key={type.id} className="flex items-center gap-2.5">
                  <Icon
                    className="h-3.5 w-3.5 shrink-0"
                    style={{ color: type.detected ? type.colour : undefined }}
                  />
                  <span className="w-32 truncate text-[0.72rem]">
                    {type.name}
                    {type.device_count > 1 ? (
                      <span className="text-muted-foreground"> ×{type.device_count}</span>
                    ) : null}
                  </span>
                  <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-secondary/70">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.max(2, type.probability * 100)}%`,
                        background: type.detected
                          ? type.colour
                          : "hsl(var(--muted-foreground) / 0.4)",
                      }}
                    />
                    <div
                      aria-hidden
                      className="absolute inset-y-0 w-px bg-foreground/50"
                      style={{ left: `${type.threshold * 100}%` }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono text-[0.68rem] tabular-nums">
                    {percent(type.probability, 0)}
                  </span>
                  {showTruth ? (
                    <span
                      className={cn(
                        "w-16 text-right text-[0.62rem]",
                        correct ? "text-success" : "text-destructive",
                      )}
                    >
                      {correct ? "correct" : type.detected ? "false +" : "missed"}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
