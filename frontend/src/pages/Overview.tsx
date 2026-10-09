import {
  Activity,
  BatteryCharging,
  Cpu,
  DoorOpen,
  IndianRupee,
  LayoutDashboard,
  Percent,
  Waves,
  Zap,
} from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { applianceIcon } from "@/lib/icons";
import { formatCurrency, formatEnergy, formatPower, percent } from "@/lib/utils";
import { useLive } from "@/state/live";

const TOP_DEVICES = 6;

/**
 * The headline numbers at a glance. Each aspect of the dashboard -- charts,
 * breakdown, waveform, controls, accuracy -- has its own page in the sidebar.
 */
export default function Overview() {
  const { frame } = useLive();

  const measurement = frame?.measurement;
  const energy = frame?.energy;
  const cost = frame?.cost;
  const symbol = cost?.currency_symbol ?? "₹";

  const power = formatPower(measurement?.power_w ?? 0);
  const todayEnergy = formatEnergy(energy?.today_wh ?? 0);
  const loadShare = energy
    ? (measurement?.power_w ?? 0) / energy.sanctioned_load_w
    : 0;

  const topDevices = useMemo(
    () =>
      (frame?.appliances ?? [])
        .filter((device) => device.detected)
        .sort((a, b) => b.estimated_power_w - a.estimated_power_w)
        .slice(0, TOP_DEVICES),
    [frame?.appliances],
  );

  const roomLoads = useMemo(() => {
    const rooms = (frame?.rooms ?? []).map((room) => ({
      ...room,
      watts: 0,
      running: 0,
      total: 0,
    }));
    const index = Object.fromEntries(rooms.map((room) => [room.id, room]));
    for (const device of frame?.appliances ?? []) {
      const room = index[device.room_id];
      if (!room) continue;
      room.total += 1;
      if (device.detected) {
        room.running += 1;
        room.watts += device.estimated_power_w;
      }
    }
    return rooms.sort((a, b) => b.watts - a.watts);
  }, [frame?.appliances, frame?.rooms]);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={LayoutDashboard}
        title="Overview"
        description="The headline numbers right now. Charts, breakdown, waveform, controls and accuracy each have their own page."
      />

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-7">
        <StatCard
          label="Live Power"
          value={power.value}
          unit={power.unit}
          icon={Zap}
          accent="#22d3ee"
          fill={loadShare}
          hint={`Real power drawn right now. The rail shows the fraction of the ${
            energy?.sanctioned_load_w.toLocaleString() ?? "—"
          } W sanctioned load in use.`}
          sub={
            energy
              ? `peak ${energy.peak_power_w.toFixed(0)} W · avg ${energy.average_power_w.toFixed(0)} W`
              : undefined
          }
        />
        <StatCard
          label="Current"
          value={(measurement?.current_a ?? 0).toFixed(2)}
          unit="A rms"
          icon={Activity}
          accent="#a78bfa"
          hint="RMS current measured at the mains — the single quantity the whole disaggregation is derived from."
          sub={
            measurement ? `peak ${measurement.peak_current_a.toFixed(2)} A` : undefined
          }
        />
        <StatCard
          label="Voltage"
          value={(measurement?.voltage_v ?? 0).toFixed(1)}
          unit="V"
          icon={Waves}
          accent="#fbbf24"
          hint="Supply voltage, sagging under the house's own load through a 0.35 Ω source impedance."
          sub={measurement ? `${measurement.frequency_hz} Hz` : undefined}
        />
        <StatCard
          label="Power Factor"
          value={(measurement?.power_factor ?? 0).toFixed(3)}
          icon={Percent}
          accent="#34d399"
          hint="Total power factor. Values below 1 with low THD mean motors; low values with high THD mean switched-mode supplies."
          sub={measurement ? `THD ${(measurement.thd * 100).toFixed(0)}%` : undefined}
        />
        <StatCard
          label="Energy Today"
          value={todayEnergy.value}
          unit={todayEnergy.unit}
          icon={BatteryCharging}
          accent="#38bdf8"
          hint="Energy accumulated since the simulated day began."
          sub={
            energy ? `${(energy.month_wh / 1000).toFixed(2)} kWh this month` : undefined
          }
        />
        <StatCard
          label="Cost Today"
          value={formatCurrency(cost?.today_inr ?? 0, symbol).replace(symbol, "")}
          unit={symbol}
          icon={IndianRupee}
          accent="#f472b6"
          hint="Charged at the marginal slab rate for this month's consumption so far."
          sub={cost ? `${symbol}${cost.marginal_rate_inr.toFixed(2)}/unit now` : undefined}
        />
        <StatCard
          label="Detection F1"
          value={percent(frame?.accuracy.f1 ?? 0, 1).replace("%", "")}
          unit="%"
          icon={Cpu}
          accent="#c084fc"
          fill={frame?.accuracy.f1 ?? 0}
          hint="Live F1 of the classifier against the simulator's hidden ground truth, over a rolling window."
          sub={frame ? `${frame.detected.length} appliances detected` : undefined}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle>
              <Zap className="h-3.5 w-3.5 text-primary" />
              Drawing the most now
            </CardTitle>
            <Link
              to="/appliances"
              className="text-[0.66rem] text-muted-foreground hover:text-foreground"
            >
              All appliances →
            </Link>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {topDevices.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                Nothing is running.
              </p>
            ) : (
              topDevices.map((device) => {
                const Icon = applianceIcon(device.icon);
                const watts = formatPower(device.estimated_power_w);
                return (
                  <Link
                    key={device.id}
                    to={`/appliances/${encodeURIComponent(device.id)}`}
                    className="flex items-center gap-2.5 rounded-md px-1.5 py-1 hover:bg-secondary/50"
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" style={{ color: device.colour }} />
                    <span className="min-w-0 flex-1 truncate text-[0.72rem]">
                      {device.name}
                    </span>
                    <span className="text-[0.62rem] text-muted-foreground">
                      {formatCurrency(device.cost_today_inr, symbol)} today
                    </span>
                    <span className="w-16 text-right font-mono text-xs font-semibold tabular-nums">
                      {watts.value} {watts.unit}
                    </span>
                  </Link>
                );
              })
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle>
              <DoorOpen className="h-3.5 w-3.5 text-primary" />
              Load by room
            </CardTitle>
            <Link
              to="/home"
              className="text-[0.66rem] text-muted-foreground hover:text-foreground"
            >
              3D Home →
            </Link>
          </CardHeader>
          <CardContent className="space-y-2">
            {roomLoads.map((room) => {
              const watts = formatPower(room.watts);
              const share = measurement?.power_w ? room.watts / measurement.power_w : 0;
              return (
                <div key={room.id} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[0.72rem] font-medium">{room.name}</span>
                    <span className="text-[0.62rem] text-muted-foreground">
                      {room.running}/{room.total} on
                    </span>
                    <span className="ml-auto font-mono text-xs font-semibold tabular-nums">
                      {watts.value}
                      <span className="ml-0.5 text-[0.62rem] font-normal text-muted-foreground">
                        {watts.unit}
                      </span>
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary/70">
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-500"
                      style={{ width: `${Math.min(100, share * 100)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
