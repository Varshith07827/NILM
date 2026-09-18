import {
  CircleDot,
  FastForward,
  Pause,
  Play,
  RotateCcw,
  Square,
  Video,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { InfoTip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { RecordingSummary, ScenarioInfo, SimulationStatus } from "@/types";

const SPEEDS = [1, 2, 5, 10, 20, 60];

const MODE_HELP: Record<string, string> = {
  demo: "Plays a fixed, hand-authored timeline of appliance events. Seeded, so every run is identical — the mode to present in.",
  simulation:
    "Each appliance decides for itself when to switch on, from its hourly usage profile. Realistic, and different every time.",
  replay:
    "Re-runs a saved recording through the live pipeline, so a demonstration can be repeated exactly.",
};

interface Props {
  status: SimulationStatus | null;
  scenarios: ScenarioInfo[];
  onChanged: () => void;
}

export function SimulationControls({ status, scenarios, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  const [recordings, setRecordings] = useState<RecordingSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const state = status?.state ?? "stopped";
  const mode = status?.mode ?? "demo";
  const recording = status?.recording;

  const loadRecordings = async () => {
    try {
      const response = await api.recordings();
      setRecordings(response.recordings);
    } catch {
      /* the panel still works without the recording list */
    }
  };

  useEffect(() => {
    void loadRecordings();
  }, [recording?.active]);

  /** Wrap every control so a failed request surfaces instead of silently doing nothing. */
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (exception) {
      setError(
        exception instanceof Error ? exception.message : "request failed",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>
          <Play className="h-3.5 w-3.5 text-primary" />
          Simulation Control
        </CardTitle>
        <Badge
          variant={
            state === "running"
              ? "success"
              : state === "paused"
                ? "warning"
                : "outline"
          }
        >
          {state}
        </Badge>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* --- transport --- */}
        <div className="grid grid-cols-4 gap-2">
          <Button
            size="sm"
            variant={state === "running" ? "secondary" : "default"}
            disabled={busy || state === "running"}
            onClick={() => run(api.start)}
          >
            <Play className="h-3.5 w-3.5" />
            Start
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || state !== "running"}
            onClick={() => run(api.pause)}
          >
            <Pause className="h-3.5 w-3.5" />
            Pause
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || state !== "paused"}
            onClick={() => run(api.resume)}
          >
            <FastForward className="h-3.5 w-3.5" />
            Resume
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => run(() => api.reset({ clear_history: true }))}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </Button>
        </div>

        {/* --- speed --- */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="label-muted">Speed</span>
            <InfoTip label="Simulated seconds per real second. Energy accounting is unaffected — one simulated second is always one watt-second.">
              <span className="cursor-help font-mono text-xs text-muted-foreground">
                {status?.speed ?? 1}x
              </span>
            </InfoTip>
          </div>
          <div className="grid grid-cols-6 gap-1">
            {SPEEDS.map((speed) => (
              <Button
                key={speed}
                size="sm"
                variant={status?.speed === speed ? "default" : "outline"}
                className="h-7 px-0 text-[0.7rem]"
                disabled={busy}
                onClick={() => run(() => api.setSpeed(speed))}
              >
                {speed}x
              </Button>
            ))}
          </div>
        </div>

        <Separator />

        {/* --- mode --- */}
        <div className="space-y-1.5">
          <span className="label-muted">Mode</span>
          <div className="grid grid-cols-3 gap-1">
            {(["demo", "simulation", "replay"] as const).map((item) => (
              <InfoTip key={item} label={MODE_HELP[item]}>
                <Button
                  size="sm"
                  variant={mode === item ? "default" : "outline"}
                  className="h-7 px-0 text-[0.7rem] capitalize"
                  disabled={
                    busy || (item === "replay" && recordings.length === 0)
                  }
                  onClick={() =>
                    run(() =>
                      api.setMode(
                        item,
                        item === "replay" ? recordings[0]?.file : undefined,
                      ),
                    )
                  }
                >
                  {item}
                </Button>
              </InfoTip>
            ))}
          </div>
          {mode === "replay" && recordings.length === 0 ? (
            <p className="text-[0.68rem] text-warning">
              Record a run first to enable replay.
            </p>
          ) : null}
        </div>

        {/* --- scenario --- */}
        <div className="space-y-1.5">
          <span className="label-muted">Scenario</span>
          <Select
            value={status?.scenario.id}
            disabled={busy}
            onValueChange={(value) => run(() => api.setScenario(value))}
          >
            <SelectTrigger>
              <SelectValue placeholder="Choose a scenario" />
            </SelectTrigger>
            <SelectContent>
              {scenarios.map((scenario) => (
                <SelectItem key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {status ? (
            <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
              {
                scenarios.find((s) => s.id === status.scenario.id)?.description
              }
            </p>
          ) : null}
        </div>

        {/* --- replay source --- */}
        {mode === "replay" && recordings.length > 0 ? (
          <div className="space-y-1.5">
            <span className="label-muted">Recording</span>
            <Select
              disabled={busy}
              onValueChange={(value) => run(() => api.setMode("replay", value))}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={recording?.name ?? "Select a recording"}
                />
              </SelectTrigger>
              <SelectContent>
                {recordings.map((item) => (
                  <SelectItem key={item.file} value={item.file}>
                    {item.name} · {item.frame_count}s
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {recording?.replay_progress != null ? (
              <div className="h-1 w-full overflow-hidden rounded-full bg-secondary">
                <div
                  className="h-full bg-accent transition-[width] duration-300"
                  style={{ width: `${recording.replay_progress * 100}%` }}
                />
              </div>
            ) : null}
          </div>
        ) : null}

        <Separator />

        {/* --- recording --- */}
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <span className="label-muted">Recorder</span>
            <p className="truncate text-[0.68rem] text-muted-foreground">
              {recording?.active
                ? `Capturing ${recording.frames} frames`
                : "Save this run for a repeatable demo"}
            </p>
          </div>
          <Button
            size="sm"
            variant={recording?.active ? "destructive" : "outline"}
            disabled={busy}
            onClick={() =>
              run(async () => {
                if (recording?.active) {
                  await api.stopRecording();
                } else {
                  await api.startRecording(
                    `${status?.scenario.id ?? "run"}-${new Date()
                      .toISOString()
                      .slice(11, 19)
                      .replace(/:/g, "")}`,
                  );
                }
                await loadRecordings();
              })
            }
          >
            {recording?.active ? (
              <>
                <Square className="h-3.5 w-3.5" />
                Stop
              </>
            ) : (
              <>
                <Video className="h-3.5 w-3.5" />
                Record
              </>
            )}
          </Button>
        </div>

        {recording?.active ? (
          <div className="flex items-center gap-1.5 text-[0.68rem] text-destructive">
            <CircleDot className={cn("h-3 w-3 animate-pulse")} />
            Recording in progress
          </div>
        ) : null}

        {error ? (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1.5 text-[0.68rem] text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
