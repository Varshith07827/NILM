import { Brain, Target } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { InfoTip } from "@/components/ui/tooltip";
import { percent } from "@/lib/utils";
import type { LiveFrame, ModelInfo } from "@/types";

/**
 * Live detector scoring plus the model card.
 *
 * The precision and recall shown here are computed on the fly by comparing the
 * classifier's output against the simulator's hidden ground truth. They are
 * not the numbers from training — they move as the scenario gets easier or
 * harder, which is exactly what makes them worth showing.
 */
export function AccuracyPanel({
  frame,
  model,
}: {
  frame: LiveFrame | null;
  model: ModelInfo | null;
}) {
  const accuracy = frame?.accuracy;
  const metrics = model?.metrics ?? {};

  const bars = [
    {
      label: "Precision",
      value: accuracy?.precision ?? 0,
      hint: "Of the appliances the model reported as running, the fraction that really were. Low precision means false alarms.",
      colour: "hsl(var(--primary))",
    },
    {
      label: "Recall",
      value: accuracy?.recall ?? 0,
      hint: "Of the appliances actually running, the fraction the model found. Low recall means missed appliances.",
      colour: "hsl(var(--accent))",
    },
    {
      label: "F1",
      value: accuracy?.f1 ?? 0,
      hint: "The harmonic mean of precision and recall — a single number that punishes being bad at either.",
      colour: "hsl(var(--success))",
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle>
          <Target className="h-3.5 w-3.5 text-primary" />
          Detector Accuracy
        </CardTitle>
        {accuracy ? (
          <InfoTip label="Scored over a rolling window of recent one-second windows.">
            <Badge variant="outline" className="cursor-help">
              last {accuracy.window}s
            </Badge>
          </InfoTip>
        ) : null}
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="space-y-2.5">
          {bars.map((bar) => (
            <div key={bar.label} className="space-y-1">
              <div className="flex items-baseline justify-between">
                <InfoTip label={bar.hint}>
                  <span className="cursor-help text-[0.7rem] font-medium text-muted-foreground">
                    {bar.label}
                  </span>
                </InfoTip>
                <span className="font-mono text-sm font-semibold tabular-nums">
                  {percent(bar.value, 1)}
                </span>
              </div>
              <Progress
                value={bar.value * 100}
                indicatorColor={bar.colour}
                className="h-1.5"
              />
            </div>
          ))}
        </div>

        {accuracy?.avg_detection_latency_s != null ? (
          <InfoTip label="How long the model takes to notice an appliance after it is switched on. The classifier looks at an eight-second sequence, so a couple of seconds is expected.">
            <div className="flex cursor-help items-center justify-between rounded-md border border-border/50 bg-secondary/30 px-2.5 py-1.5">
              <span className="text-[0.68rem] text-muted-foreground">
                Detection latency
              </span>
              <span className="font-mono text-xs font-semibold tabular-nums">
                {accuracy.avg_detection_latency_s.toFixed(1)} s
              </span>
            </div>
          </InfoTip>
        ) : null}

        <Separator />

        {/* --- model card --- */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <Brain className="h-3.5 w-3.5 text-accent" />
            <span className="label-muted">Model</span>
          </div>

          {model?.model_available ? (
            <div className="space-y-1.5 text-[0.7rem]">
              <Row label="Architecture" value={model.architecture} mono={false} />
              <Row
                label="Parameters"
                value={model.parameters.toLocaleString()}
              />
              <Row
                label="Input"
                value={`${model.sequence_length} x ${model.num_features}`}
              />
              <Row label="Runtime" value={model.backend} mono={false} />
              {metrics.macro_f1 ? (
                <Row
                  label="Validation macro-F1"
                  value={percent(metrics.macro_f1, 1)}
                />
              ) : null}
              {metrics.hamming_accuracy ? (
                <Row
                  label="Validation accuracy"
                  value={percent(metrics.hamming_accuracy, 1)}
                />
              ) : null}
              {frame ? (
                <Row
                  label="Inference"
                  value={`${frame.inference.median_latency_ms.toFixed(2)} ms`}
                />
              ) : null}
            </div>
          ) : (
            <div className="rounded-md border border-warning/30 bg-warning/10 p-2.5">
              <p className="text-[0.7rem] font-medium text-warning">
                Running the classical solver
              </p>
              <p className="mt-1 text-[0.68rem] leading-relaxed text-muted-foreground">
                No trained model found, so detection is falling back to
                non-negative harmonic least squares. Train one with{" "}
                <code className="rounded bg-secondary px-1 py-0.5 font-mono">
                  python -m ai.train
                </code>
                .
              </p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Row({
  label,
  value,
  mono = true,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={
          mono
            ? "truncate font-mono text-[0.7rem] font-medium tabular-nums"
            : "truncate text-[0.7rem] font-medium"
        }
      >
        {value}
      </span>
    </div>
  );
}
