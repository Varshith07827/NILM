import { PieChart } from "lucide-react";
import { useMemo } from "react";
import { Doughnut } from "react-chartjs-2";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { doughnutOptions } from "@/lib/charts";
import { formatCurrency, formatEnergy, percent } from "@/lib/utils";
import type { LiveFrame } from "@/types";

const UNATTRIBUTED_COLOUR = "#64748b";

/**
 * Where today's energy actually went.
 *
 * The "Unattributed" slice is deliberately shown rather than hidden. It is the
 * power the disaggregator could not confidently assign to any detected
 * appliance, and a NILM dashboard that always sums to a tidy 100% of named
 * appliances is not being honest about its own uncertainty.
 */
export function EnergyBreakdown({ frame }: { frame: LiveFrame | null }) {
  const rows = useMemo(() => {
    if (!frame) return [];
    const items = frame.appliances
      .filter((appliance) => appliance.energy_wh_today > 0.001)
      .map((appliance) => ({
        id: appliance.id,
        name: appliance.name,
        colour: appliance.colour,
        energy: appliance.energy_wh_today,
        cost: appliance.cost_today_inr,
      }))
      .sort((a, b) => b.energy - a.energy);

    const named = items.reduce((sum, item) => sum + item.energy, 0);
    const remainder = Math.max(0, frame.energy.today_wh - named);
    if (remainder > 0.001) {
      items.push({
        id: "__unattributed__",
        name: "Unattributed",
        colour: UNATTRIBUTED_COLOUR,
        energy: remainder,
        cost: 0,
      });
    }
    return items;
  }, [frame]);

  const total = rows.reduce((sum, row) => sum + row.energy, 0);

  const chart = useMemo(
    () => ({
      labels: rows.map((row) => row.name),
      datasets: [
        {
          data: rows.map((row) => row.energy),
          backgroundColor: rows.map((row) => row.colour),
          borderColor: "hsl(var(--card))",
          borderWidth: 2,
          hoverOffset: 6,
        },
      ],
    }),
    [rows],
  );

  const options = useMemo(() => {
    const base = doughnutOptions();
    return {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          ...base.plugins?.tooltip,
          callbacks: {
            label(context: { label?: string; parsed: number }) {
              const wh = context.parsed;
              const formatted = formatEnergy(wh);
              const share = total > 0 ? percent(wh / total, 1) : "0%";
              return ` ${context.label}: ${formatted.value} ${formatted.unit} (${share})`;
            },
          },
        },
      },
    };
  }, [total]);

  const totalFormatted = formatEnergy(total);

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle>
          <PieChart className="h-3.5 w-3.5 text-primary" />
          Energy Breakdown
        </CardTitle>
        <p className="text-[0.68rem] text-muted-foreground">
          Disaggregated consumption for the simulated day
        </p>
      </CardHeader>

      <CardContent>
        {rows.length === 0 ? (
          <div className="flex h-[180px] items-center justify-center text-xs text-muted-foreground">
            No energy recorded yet
          </div>
        ) : (
          <>
            <div className="relative mx-auto h-[180px]">
              <Doughnut data={chart} options={options} />
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="font-mono text-xl font-bold tabular-nums">
                  {totalFormatted.value}
                </span>
                <span className="text-[0.65rem] text-muted-foreground">
                  {totalFormatted.unit} today
                </span>
              </div>
            </div>

            <ScrollArea className="mt-3 max-h-[190px]">
              <div className="space-y-1 pr-2">
                {rows.map((row) => {
                  const share = total > 0 ? row.energy / total : 0;
                  const formatted = formatEnergy(row.energy);
                  return (
                    <div
                      key={row.id}
                      className="flex items-center gap-2 rounded-md px-1.5 py-1 transition-colors hover:bg-secondary/40"
                    >
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: row.colour }}
                      />
                      <span className="min-w-0 flex-1 truncate text-[0.7rem]">
                        {row.name}
                      </span>
                      <span className="font-mono text-[0.68rem] tabular-nums text-muted-foreground">
                        {formatted.value} {formatted.unit}
                      </span>
                      <span className="w-10 text-right font-mono text-[0.68rem] tabular-nums">
                        {percent(share, 0)}
                      </span>
                      {row.cost > 0 ? (
                        <span className="w-12 text-right font-mono text-[0.68rem] tabular-nums text-muted-foreground">
                          {formatCurrency(
                            row.cost,
                            frame?.cost.currency_symbol ?? "₹",
                          )}
                        </span>
                      ) : (
                        <span className="w-12" />
                      )}
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </>
        )}
      </CardContent>
    </Card>
  );
}
