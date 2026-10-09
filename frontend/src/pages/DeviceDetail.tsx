/**
 * One device: its live current and power, energy, cost, and history.
 *
 * The live traces come from the frame history already in the browser, so they
 * move with the rest of the dashboard. The hourly energy and cost come from
 * the database and are refreshed every few seconds.
 *
 * Every figure here is an *estimate*: the meter measures only the house total,
 * and this device's share of it is worked out by disaggregation.
 */

import {
  ArrowLeft,
  BatteryCharging,
  Clock,
  IndianRupee,
  Power,
  Waves,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, Line } from "react-chartjs-2";
import { Link, useParams } from "react-router-dom";

import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { api } from "@/lib/api";
import { barOptions, baseLineOptions, CHART_COLORS } from "@/lib/charts";
import { applianceIcon } from "@/lib/icons";
import {
  formatClock,
  formatCurrency,
  formatDuration,
  formatEnergy,
  formatPower,
  hexToRgba,
  percent,
} from "@/lib/utils";
import { useLive } from "@/state/live";
import type { DeviceHistory } from "@/types";

const LIVE_WINDOW = 300;
const HISTORY_REFRESH_MS = 8000;

export default function DeviceDetail() {
  const { deviceId = "" } = useParams();
  const { frame, history, showTruth, onChanged } = useLive();
  const [stored, setStored] = useState<DeviceHistory | null>(null);
  const [busy, setBusy] = useState(false);

  const device = frame?.appliances.find((a) => a.id === deviceId) ?? null;
  const symbol = frame?.cost.currency_symbol ?? "₹";

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .deviceHistory(deviceId)
        .then((response) => !cancelled && setStored(response))
        .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, HISTORY_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [deviceId]);

  const live = useMemo(() => {
    const frames = history.slice(-LIVE_WINDOW);
    const rows = frames.map((f) => f.appliances.find((a) => a.id === deviceId));
    return {
      labels: frames.map((f) => formatClock(f.sim_time)),
      power: rows.map((row) => row?.estimated_power_w ?? 0),
      current: rows.map((row) => row?.estimated_current_a ?? 0),
      actual: rows.map((row) => row?.actual_power_w ?? 0),
    };
  }, [history, deviceId]);

  if (!device) {
    return (
      <div className="space-y-4">
        <BackLink />
        <p className="py-12 text-center text-sm text-muted-foreground">
          {frame
            ? "No such device in the house. It may have been removed."
            : "Waiting for the first acquisition window…"}
        </p>
      </div>
    );
  }

  const colour = device.colour;
  const power = formatPower(device.estimated_power_w);
  const energy = formatEnergy(device.energy_wh_today);

  const toggle = async () => {
    setBusy(true);
    try {
      await api.toggleAppliance(device.id, !device.socket_on);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const powerChart = {
    labels: live.labels,
    datasets: [
      {
        label: "Estimated power (W)",
        data: live.power,
        borderColor: colour,
        backgroundColor: hexToRgba(colour, 0.12),
        fill: true,
      },
      ...(showTruth
        ? [
            {
              label: "Actual (simulator)",
              data: live.actual,
              borderColor: CHART_COLORS.voltage,
              borderDash: [4, 4],
              backgroundColor: "transparent",
              fill: false,
            },
          ]
        : []),
    ],
  };

  const currentChart = {
    labels: live.labels,
    datasets: [
      {
        label: "Estimated current (A)",
        data: live.current,
        borderColor: CHART_COLORS.current,
        backgroundColor: hexToRgba(CHART_COLORS.current, 0.12),
        fill: true,
      },
    ],
  };

  const hourly = stored?.hourly ?? [];
  const hourlyChart = {
    labels: hourly.map((row) => formatClock(row.bucket_start).slice(0, 5)),
    datasets: [
      {
        label: `Cost (${symbol})`,
        data: hourly.map((row) => row.cost_inr),
        backgroundColor: hexToRgba(colour, 0.7),
        borderRadius: 4,
      },
    ],
  };

  const Icon = applianceIcon(device.icon);

  return (
    <div className="space-y-4">
      <BackLink />
      <PageHeader
        icon={Icon}
        title={device.name}
        description={`${device.type_name} in the ${device.room_name}, rated ${device.rated_power_w} W. Figures are this device's estimated share of the single mains measurement.`}
        actions={
          <>
            <Badge variant={device.detected ? "success" : "secondary"}>
              {device.detected ? "running" : "off"}
            </Badge>
            <Button
              size="sm"
              variant={device.socket_on ? "destructive" : "success"}
              disabled={busy}
              onClick={() => void toggle()}
            >
              <Power className="h-3.5 w-3.5" />
              Switch {device.socket_on ? "off" : "on"}
            </Button>
          </>
        }
      />

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="Power"
          value={power.value}
          unit={power.unit}
          icon={Zap}
          accent={colour}
          fill={device.rated_power_w ? device.estimated_power_w / device.rated_power_w : 0}
          hint="Estimated real power drawn by this device right now."
          sub={showTruth ? `true ${device.actual_power_w.toFixed(0)} W` : undefined}
        />
        <StatCard
          label="Current"
          value={device.estimated_current_a.toFixed(3)}
          unit="A"
          icon={Waves}
          accent="#a78bfa"
          hint="Estimated power divided by supply voltage and this device's power factor."
          sub={showTruth ? `true ${device.actual_current_a.toFixed(3)} A` : undefined}
        />
        <StatCard
          label="Energy today"
          value={energy.value}
          unit={energy.unit}
          icon={BatteryCharging}
          accent="#38bdf8"
        />
        <StatCard
          label="Cost today"
          value={formatCurrency(device.cost_today_inr, symbol).replace(symbol, "")}
          unit={symbol}
          icon={IndianRupee}
          accent="#f472b6"
          hint="This device's share of today's bill, priced at the marginal slab rate."
        />
        <StatCard
          label="Cost this month"
          value={formatCurrency(device.cost_month_inr, symbol).replace(symbol, "")}
          unit={symbol}
          icon={IndianRupee}
          accent="#fb923c"
        />
        <StatCard
          label="Runtime today"
          value={formatDuration(device.runtime_s_today)}
          icon={Clock}
          accent="#34d399"
          sub={`${device.type_name} confidence ${percent(device.probability, 0)}`}
        />
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Power">
          <Line data={powerChart} options={baseLineOptions({ yTitle: "W" })} />
        </ChartCard>
        <ChartCard title="Current">
          <Line data={currentChart} options={baseLineOptions({ yTitle: "A" })} />
        </ChartCard>
      </div>

      <ChartCard title="Cost by hour">
        {hourly.length ? (
          <Bar data={hourlyChart} options={barOptions(symbol)} />
        ) : (
          <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
            No completed hours yet for this run.
          </p>
        )}
      </ChartCard>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-56">{children}</div>
      </CardContent>
    </Card>
  );
}

function BackLink() {
  return (
    <Link
      to="/appliances"
      className="inline-flex items-center gap-1 text-[0.7rem] text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3 w-3" />
      All appliances
    </Link>
  );
}
