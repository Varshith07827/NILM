import { Receipt } from "lucide-react";
import { useMemo } from "react";

import { CostPanel } from "@/components/CostPanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { PageHeader } from "@/components/layout/PageHeader";
import { formatCurrency, formatDuration, formatEnergy } from "@/lib/utils";
import { useLive } from "@/state/live";

export default function Billing() {
  const { frame, onChanged } = useLive();
  const symbol = frame?.cost.currency_symbol ?? "₹";

  const rows = useMemo(() => {
    const appliances = frame?.appliances ?? [];
    return appliances
      .filter((appliance) => appliance.energy_wh_today > 0.001)
      .map((appliance) => ({
        id: appliance.id,
        name: appliance.name,
        colour: appliance.colour,
        energy: appliance.energy_wh_today,
        cost: appliance.cost_today_inr,
        runtime: appliance.runtime_s_today,
      }))
      .sort((a, b) => b.cost - a.cost);
  }, [frame?.appliances]);

  const totalCost = rows.reduce((sum, row) => sum + row.cost, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Receipt}
        title="Billing"
        description="What the electricity actually costs, under real telescopic slab tariffs — and which appliance is responsible for it."
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-5">
          <CostPanel frame={frame} onChanged={onChanged} />
        </div>

        <Card className="xl:col-span-7">
          <CardHeader className="pb-3">
            <CardTitle>Cost by Appliance — Today</CardTitle>
            <p className="text-[0.68rem] text-muted-foreground">
              Each appliance is charged its share of the marginal slab rate at
              the moment it consumed the energy, so the parts add up to the
              metered whole.
            </p>
          </CardHeader>
          <CardContent>
            <ScrollArea className="max-h-[430px]">
              <table className="w-full text-[0.7rem]">
                <thead className="sticky top-0 bg-card/95 text-muted-foreground backdrop-blur">
                  <tr className="border-b border-border/60">
                    <th className="py-2 text-left font-medium">Appliance</th>
                    <th className="py-2 text-right font-medium">Energy</th>
                    <th className="py-2 text-right font-medium">Runtime</th>
                    <th className="py-2 text-right font-medium">Cost</th>
                    <th className="py-2 text-right font-medium">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const energy = formatEnergy(row.energy);
                    const share = totalCost > 0 ? row.cost / totalCost : 0;
                    return (
                      <tr
                        key={row.id}
                        className="border-b border-border/25 transition-colors hover:bg-secondary/30"
                      >
                        <td className="py-1.5">
                          <span className="flex items-center gap-1.5">
                            <span
                              className="h-2 w-2 shrink-0 rounded-full"
                              style={{ background: row.colour }}
                            />
                            <span className="truncate">{row.name}</span>
                          </span>
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums">
                          {energy.value} {energy.unit}
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                          {formatDuration(row.runtime)}
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums">
                          {formatCurrency(row.cost, symbol)}
                        </td>
                        <td className="py-1.5 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <div className="h-1 w-12 overflow-hidden rounded-full bg-secondary">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${share * 100}%`,
                                  background: row.colour,
                                }}
                              />
                            </div>
                            <span className="w-9 font-mono tabular-nums">
                              {(share * 100).toFixed(0)}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        className="py-8 text-center text-muted-foreground"
                      >
                        No consumption recorded yet today.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
