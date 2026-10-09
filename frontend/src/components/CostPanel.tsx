import { IndianRupee, Lock, Receipt } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
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
import { cn, formatCurrency } from "@/lib/utils";
import { useAuth } from "@/state/auth";
import type { LiveFrame, SlabRow, Tariff } from "@/types";

/**
 * Cost, and the slab arithmetic behind it.
 *
 * The slab table is not decoration. Indian domestic tariffs are telescopic, so
 * the cost of the next unit depends on how much has already been used this
 * month. Showing which band is currently active explains why the cost line on
 * the energy chart changes slope partway through a long run.
 */
export function CostPanel({
  frame,
  onChanged,
}: {
  frame: LiveFrame | null;
  onChanged: () => void;
}) {
  const [tariffs, setTariffs] = useState<Tariff[]>([]);
  const [slabs, setSlabs] = useState<SlabRow[]>([]);
  const [activeTariff, setActiveTariff] = useState<Tariff | null>(null);
  const [busy, setBusy] = useState(false);
  const { admin } = useAuth();

  useEffect(() => {
    void api.tariffs().then(setTariffs).catch(() => undefined);
  }, []);

  // The slab breakdown is not in the live frame (it changes slowly and would
  // bloat every window), so it is polled at a much lower rate.
  useEffect(() => {
    const refresh = () =>
      api
        .cost()
        .then((response) => {
          setSlabs(response.slab_breakdown);
          setActiveTariff(response.tariff);
        })
        .catch(() => undefined);

    void refresh();
    const timer = window.setInterval(refresh, 4000);
    return () => window.clearInterval(timer);
  }, []);

  const symbol = frame?.cost.currency_symbol ?? "₹";
  const cost = frame?.cost;

  const changeTariff = async (tariffId: string) => {
    setBusy(true);
    try {
      await api.setTariff({ tariff_id: tariffId });
      setActiveTariff(tariffs.find((t) => t.id === tariffId) ?? null);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle>
          <Receipt className="h-3.5 w-3.5 text-primary" />
          Electricity Cost
        </CardTitle>
        {cost ? (
          <InfoTip label="The rate the next unit will be charged at, given this month's consumption so far.">
            <Badge variant="outline" className="cursor-help">
              {symbol}
              {cost.marginal_rate_inr.toFixed(2)}/unit
            </Badge>
          </InfoTip>
        ) : null}
      </CardHeader>

      <CardContent className="space-y-4">
        {/* --- headline figures --- */}
        <div className="grid grid-cols-2 gap-2">
          <Figure
            label="Today"
            value={formatCurrency(cost?.today_inr ?? 0, symbol)}
            accent
          />
          <Figure
            label="This month"
            value={formatCurrency(cost?.month_inr ?? 0, symbol)}
          />
          <Figure
            label="Monthly bill"
            value={formatCurrency(cost?.monthly_bill_inr ?? 0, symbol)}
            hint="Energy charge for the month so far, plus the fixed standing charge."
          />
          <Figure
            label="Projected"
            value={formatCurrency(cost?.projected_month_inr ?? 0, symbol)}
            hint="Extrapolates the consumption rate observed so far across a full 30-day month."
          />
        </div>

        <Separator />

        {/* --- tariff: chosen by the admin, shown to everyone --- */}
        <div className="space-y-1.5">
          <span className="label-muted">Tariff</span>
          {admin ? (
            <Select
              value={activeTariff?.id ?? ""}
              disabled={busy}
              onValueChange={(value) => void changeTariff(value)}
            >
              <SelectTrigger>
                <SelectValue placeholder={activeTariff?.name ?? "Select a tariff"} />
              </SelectTrigger>
              <SelectContent>
                {tariffs.map((tariff) => (
                  <SelectItem key={tariff.id} value={tariff.id}>
                    {tariff.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-secondary/30 px-3 py-2 text-xs">
              <span className="font-medium">{activeTariff?.name ?? "—"}</span>
              <Link
                to="/admin"
                className="flex items-center gap-1 text-[0.66rem] text-muted-foreground hover:text-foreground"
              >
                <Lock className="h-3 w-3" />
                Admin can change
              </Link>
            </div>
          )}
          <p className="text-[0.66rem] leading-relaxed text-muted-foreground">
            {activeTariff?.description}
          </p>
        </div>

        {/* --- slab table --- */}
        {slabs.length > 1 ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <IndianRupee className="h-3 w-3 text-muted-foreground" />
              <span className="label-muted">Slab breakdown</span>
            </div>
            <div className="overflow-hidden rounded-lg border border-border/60">
              <table className="w-full text-[0.66rem]">
                <thead className="bg-secondary/50 text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1 text-left font-medium">Band</th>
                    <th className="px-2 py-1 text-right font-medium">Rate</th>
                    <th className="px-2 py-1 text-right font-medium">Units</th>
                    <th className="px-2 py-1 text-right font-medium">Charge</th>
                  </tr>
                </thead>
                <tbody>
                  {slabs.map((slab, index) => (
                    <tr
                      key={index}
                      className={cn(
                        "border-t border-border/40 transition-colors",
                        slab.active && "bg-primary/10 font-medium text-primary",
                      )}
                    >
                      <td className="px-2 py-1 font-mono tabular-nums">
                        {slab.from_kwh}–{slab.to_kwh ?? "∞"}
                      </td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">
                        {slab.rate_inr.toFixed(2)}
                      </td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">
                        {slab.units < 0.01 && slab.units > 0
                          ? slab.units.toFixed(4)
                          : slab.units.toFixed(2)}
                      </td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">
                        {slab.charge_inr.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[0.64rem] leading-relaxed text-muted-foreground">
              Telescopic tariff: bands apply progressively, like tax brackets.
              The highlighted row is where the next unit will be charged.
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Figure({
  label,
  value,
  accent,
  hint,
}: {
  label: string;
  value: string;
  accent?: boolean;
  hint?: string;
}) {
  const body = (
    <div
      className={cn(
        "rounded-lg border px-2.5 py-2",
        accent
          ? "border-primary/25 bg-primary/10"
          : "border-border/50 bg-secondary/30",
        hint && "cursor-help",
      )}
    >
      <p className="text-[0.62rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-0.5 font-mono text-base font-semibold tabular-nums",
          accent && "text-primary",
        )}
      >
        {value}
      </p>
    </div>
  );
  return hint ? <InfoTip label={hint}>{body}</InfoTip> : body;
}
