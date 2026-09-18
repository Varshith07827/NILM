import {
  Activity,
  BatteryCharging,
  Cpu,
  IndianRupee,
  LayoutDashboard,
  Percent,
  Waves,
  Zap,
} from "lucide-react";

import { EnergyBreakdown } from "@/components/EnergyBreakdown";
import { LiveCharts } from "@/components/LiveCharts";
import { SimulationControls } from "@/components/SimulationControls";
import { StatCard } from "@/components/StatCard";
import { PageHeader } from "@/components/layout/PageHeader";
import { formatCurrency, formatEnergy, formatPower, percent } from "@/lib/utils";
import { useLive } from "@/state/live";

export default function Overview() {
  const { frame, history, status, scenarios, onChanged } = useLive();

  const measurement = frame?.measurement;
  const energy = frame?.energy;
  const cost = frame?.cost;
  const symbol = cost?.currency_symbol ?? "₹";

  const power = formatPower(measurement?.power_w ?? 0);
  const todayEnergy = formatEnergy(energy?.today_wh ?? 0);
  const loadShare = energy
    ? (measurement?.power_w ?? 0) / energy.sanctioned_load_w
    : 0;

  return (
    <div className="space-y-4">
      <PageHeader
        icon={LayoutDashboard}
        title="Overview"
        description="Everything the meter sees right now, and what the model makes of it."
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

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="space-y-4 xl:col-span-8">
          <LiveCharts history={history} />
          <EnergyBreakdown frame={frame} />
        </div>
        <div className="xl:col-span-4">
          <SimulationControls
            status={status}
            scenarios={scenarios}
            onChanged={onChanged}
          />
        </div>
      </section>
    </div>
  );
}
