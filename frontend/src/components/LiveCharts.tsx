import { Activity, Gauge, TrendingUp, Waves } from "lucide-react";
import { useMemo } from "react";
import { Line } from "react-chartjs-2";

import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { CHART_COLORS, baseLineOptions } from "@/lib/charts";
import { formatClock, hexToRgba } from "@/lib/utils";
import type { LiveFrame } from "@/types";

interface Props {
  history: LiveFrame[];
  /** Points to plot. Fewer points redraw faster and read more clearly. */
  window?: number;
}

export function LiveCharts({ history, window: windowSize = 180 }: Props) {
  const slice = useMemo(
    () => history.slice(-windowSize),
    [history, windowSize],
  );

  const labels = useMemo(
    () => slice.map((frame) => formatClock(frame.sim_time)),
    [slice],
  );

  const powerData = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: "Real power (W)",
          data: slice.map((f) => f.measurement.power_w),
          borderColor: CHART_COLORS.power,
          backgroundColor: hexToRgba(CHART_COLORS.power, 0.16),
          fill: true,
        },
        {
          label: "Apparent power (VA)",
          data: slice.map((f) => f.measurement.apparent_va),
          borderColor: CHART_COLORS.reactive,
          backgroundColor: "transparent",
          borderDash: [4, 3],
          fill: false,
        },
      ],
    }),
    [labels, slice],
  );

  const currentData = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: "RMS current (A)",
          data: slice.map((f) => f.measurement.current_a),
          borderColor: CHART_COLORS.current,
          backgroundColor: hexToRgba(CHART_COLORS.current, 0.16),
          fill: true,
          yAxisID: "y",
        },
        {
          label: "Peak current (A)",
          data: slice.map((f) => f.measurement.peak_current_a),
          borderColor: hexToRgba(CHART_COLORS.current, 0.5),
          backgroundColor: "transparent",
          borderDash: [3, 3],
          fill: false,
          yAxisID: "y",
        },
      ],
    }),
    [labels, slice],
  );

  const energyData = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: "Energy today (Wh)",
          data: slice.map((f) => f.energy.today_wh),
          borderColor: CHART_COLORS.energy,
          backgroundColor: hexToRgba(CHART_COLORS.energy, 0.2),
          fill: true,
          yAxisID: "y",
        },
        {
          label: "Cost today",
          data: slice.map((f) => f.cost.today_inr),
          borderColor: CHART_COLORS.cost,
          backgroundColor: "transparent",
          fill: false,
          yAxisID: "y1",
        },
      ],
    }),
    [labels, slice],
  );

  const qualityData = useMemo(
    () => ({
      labels,
      datasets: [
        {
          label: "Power factor",
          data: slice.map((f) => f.measurement.power_factor),
          borderColor: CHART_COLORS.voltage,
          backgroundColor: hexToRgba(CHART_COLORS.voltage, 0.15),
          fill: true,
          yAxisID: "y",
        },
        {
          label: "Current THD",
          data: slice.map((f) => f.measurement.thd),
          borderColor: CHART_COLORS.reactive,
          backgroundColor: "transparent",
          fill: false,
          yAxisID: "y",
        },
        {
          label: "Voltage (V)",
          data: slice.map((f) => f.measurement.voltage_v),
          borderColor: hexToRgba("#94a3b8", 0.85),
          backgroundColor: "transparent",
          borderDash: [4, 3],
          fill: false,
          yAxisID: "y1",
        },
      ],
    }),
    [labels, slice],
  );

  const dualAxis = (leftTitle: string, rightTitle: string) => {
    const options = baseLineOptions({ yTitle: leftTitle });
    return {
      ...options,
      scales: {
        ...options.scales,
        y1: {
          position: "right" as const,
          beginAtZero: false,
          grid: { display: false },
          border: { display: false },
          ticks: { maxTicksLimit: 5 },
          title: { display: true, text: rightTitle, font: { size: 9 } },
        },
      },
    };
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <Tabs defaultValue="power">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>
              <Activity className="h-3.5 w-3.5 text-primary" />
              Live Measurements
            </CardTitle>
            <TabsList>
              <TabsTrigger value="power">
                <TrendingUp />
                Power
              </TabsTrigger>
              <TabsTrigger value="current">
                <Activity />
                Current
              </TabsTrigger>
              <TabsTrigger value="energy">
                <Gauge />
                Energy
              </TabsTrigger>
              <TabsTrigger value="quality">
                <Waves />
                Quality
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="power">
            <div className="h-[260px]">
              <Line data={powerData} options={baseLineOptions({ yTitle: "W / VA" })} />
            </div>
            <p className="mt-1 text-[0.68rem] text-muted-foreground">
              The gap between real power and apparent power is the non-active
              power the household draws but is not billed for as energy.
            </p>
          </TabsContent>

          <TabsContent value="current">
            <div className="h-[260px]">
              <Line
                data={currentData}
                options={baseLineOptions({ yTitle: "Amperes" })}
              />
            </div>
            <p className="mt-1 text-[0.68rem] text-muted-foreground">
              Spikes where peak separates sharply from RMS are motor and
              compressor inrush — the transients the classifier keys on.
            </p>
          </TabsContent>

          <TabsContent value="energy">
            <div className="h-[260px]">
              <Line data={energyData} options={dualAxis("Wh", "Cost")} />
            </div>
            <p className="mt-1 text-[0.68rem] text-muted-foreground">
              Cost accrues at the marginal slab rate for the month so far, so
              its slope steepens as consumption crosses a slab boundary.
            </p>
          </TabsContent>

          <TabsContent value="quality">
            <div className="h-[260px]">
              <Line data={qualityData} options={dualAxis("PF / THD", "Volts")} />
            </div>
            <p className="mt-1 text-[0.68rem] text-muted-foreground">
              Voltage sags as load rises — the supply has a finite source
              impedance, modelled here at 0.35 Ω.
            </p>
          </TabsContent>
        </Tabs>
      </CardHeader>
    </Card>
  );
}
