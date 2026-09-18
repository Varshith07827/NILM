import { Radio } from "lucide-react";
import { useMemo } from "react";
import type { ChartOptions } from "chart.js";
import { Line } from "react-chartjs-2";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InfoTip } from "@/components/ui/tooltip";
import { baseLineOptions, themeColor } from "@/lib/charts";
import type { LiveFrame } from "@/types";

/**
 * The raw 50 Hz waveform, straight off the "sensor".
 *
 * This is the panel that makes the project legible in a demo: everything else
 * on the dashboard is derived, but this is the actual signal the whole system
 * has to work from. Watching the current waveform go from a clean sinusoid to
 * a spiky, distorted shape as an SMPS load switches on is the argument for
 * harmonic-based disaggregation in a single picture.
 */
export function Oscilloscope({ frame }: { frame: LiveFrame | null }) {
  const data = useMemo(() => {
    if (!frame) return null;
    const { current, voltage, sample_rate_hz } = frame.scope;
    const labels = current.map((_, index) =>
      ((index / sample_rate_hz) * 1000).toFixed(1),
    );

    return {
      labels,
      datasets: [
        {
          label: "Current (A)",
          data: current,
          borderColor: "#22d3ee",
          backgroundColor: "rgba(34, 211, 238, 0.12)",
          fill: true,
          yAxisID: "y",
          borderWidth: 1.8,
        },
        {
          label: "Voltage (V)",
          data: voltage,
          borderColor: "rgba(251, 191, 36, 0.7)",
          backgroundColor: "transparent",
          fill: false,
          yAxisID: "y1",
          borderWidth: 1.2,
        },
      ],
    };
  }, [frame]);

  const sampleRate = frame?.scope.sample_rate_hz ?? 2000;

  const options = useMemo<ChartOptions<"line">>(() => {
    const base = baseLineOptions({ yTitle: "Amperes", beginAtZero: false });
    // One tick every 2 ms keeps the axis readable at 40 samples per cycle.
    const samplesPerTick = Math.max(1, Math.round(sampleRate / 500));

    return {
      ...base,
      elements: {
        line: { borderWidth: 1.6, tension: 0.1 },
        point: { radius: 0, hoverRadius: 0, hitRadius: 4 },
      },
      scales: {
        y: base.scales?.y,
        x: {
          grid: { display: false },
          ticks: {
            color: themeColor("--muted-foreground", 0.95),
            maxRotation: 0,
            autoSkip: false,
            callback: (_value, index) =>
              index % samplesPerTick === 0
                ? `${((index / sampleRate) * 1000).toFixed(0)}`
                : "",
          },
          title: { display: true, text: "milliseconds", font: { size: 9 } },
        },
        y1: {
          position: "right",
          beginAtZero: false,
          grid: { display: false },
          border: { display: false },
          ticks: { maxTicksLimit: 5 },
          title: { display: true, text: "Volts", font: { size: 9 } },
        },
      },
    };
  }, [sampleRate]);

  return (
    <Card className="h-full">
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
        <div className="space-y-1">
          <CardTitle>
            <Radio className="h-3.5 w-3.5 text-primary" />
            Raw Waveform
          </CardTitle>
          <p className="text-[0.68rem] text-muted-foreground">
            Two mains cycles as the clamp sensor sees them
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <InfoTip label="Sampling rate of the simulated ESP32 ADC. 40 samples per cycle puts Nyquist at 1 kHz, enough for every harmonic the model uses.">
            <Badge variant="outline" className="cursor-help">
              {frame ? `${frame.scope.sample_rate_hz / 1000} kS/s` : "—"}
            </Badge>
          </InfoTip>
          {frame ? (
            <InfoTip label="Crest factor is peak current over RMS current. A pure sinusoid is 1.41; switched-mode supplies push it well past 2.">
              <Badge
                variant={
                  frame.measurement.crest_factor > 2 ? "accent" : "secondary"
                }
                className="cursor-help"
              >
                CF {frame.measurement.crest_factor.toFixed(2)}
              </Badge>
            </InfoTip>
          ) : null}
        </div>
      </CardHeader>

      <CardContent>
        <div className="h-[200px]">
          {data ? (
            <Line data={data} options={options} />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
              Waiting for the first acquisition window…
            </div>
          )}
        </div>

        {frame ? (
          <div className="mt-2 grid grid-cols-4 gap-2 text-center">
            {[
              {
                label: "THD",
                value: `${(frame.measurement.thd * 100).toFixed(0)}%`,
                hint: "Total harmonic distortion of the current waveform.",
              },
              {
                label: "PF",
                value: frame.measurement.power_factor.toFixed(3),
                hint: "Total power factor: displacement times distortion.",
              },
              {
                label: "V rms",
                value: `${frame.measurement.voltage_v.toFixed(1)}`,
                hint: "Supply voltage after the sag caused by this house's own load.",
              },
              {
                label: "I peak",
                value: `${frame.measurement.peak_current_a.toFixed(2)}`,
                hint: "Highest instantaneous current in the window — this is where inrush shows up.",
              },
            ].map((item) => (
              <InfoTip key={item.label} label={item.hint}>
                <div className="cursor-help rounded-md border border-border/50 bg-secondary/30 px-2 py-1.5">
                  <p className="text-[0.6rem] uppercase tracking-wider text-muted-foreground">
                    {item.label}
                  </p>
                  <p className="font-mono text-xs font-semibold tabular-nums">
                    {item.value}
                  </p>
                </div>
              </InfoTip>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
