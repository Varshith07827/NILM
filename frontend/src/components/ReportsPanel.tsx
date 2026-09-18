import { Download, FileSpreadsheet, FileText, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Bar } from "react-chartjs-2";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { barOptions } from "@/lib/charts";
import { api } from "@/lib/api";
import { cn, formatCurrency, formatDuration } from "@/lib/utils";
import type { Report } from "@/types";

type Period = "daily" | "weekly" | "monthly";

export function ReportsPanel() {
  const [period, setPeriod] = useState<Period>("daily");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (target: Period) => {
    setLoading(true);
    try {
      setReport(await api.report(target));
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(period);
    // Reports aggregate persisted data, which only changes as the simulation
    // writes batches; refreshing every ten seconds is plenty.
    const timer = window.setInterval(() => void load(period), 10_000);
    return () => window.clearInterval(timer);
  }, [period, load]);

  const symbol = report?.tariff.currency_symbol ?? "₹";

  const hourly = report?.hourly ?? [];
  const chart = {
    labels: hourly.map((row) =>
      new Date(row.bucket_start).toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    ),
    datasets: [
      {
        label: "Energy (Wh)",
        data: hourly.map((row) => row.energy_wh),
        backgroundColor: "rgba(34, 211, 238, 0.55)",
        hoverBackgroundColor: "rgba(34, 211, 238, 0.85)",
        borderRadius: 3,
        borderSkipped: false as const,
      },
    ],
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>
            <FileText className="h-3.5 w-3.5 text-primary" />
            Reports
          </CardTitle>
          <div className="flex items-center gap-2">
            <Tabs
              value={period}
              onValueChange={(value) => setPeriod(value as Period)}
            >
              <TabsList>
                <TabsTrigger value="daily">Daily</TabsTrigger>
                <TabsTrigger value="weekly">Weekly</TabsTrigger>
                <TabsTrigger value="monthly">Monthly</TabsTrigger>
              </TabsList>
            </Tabs>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => void load(period)}
              aria-label="Refresh report"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* --- summary --- */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Summary
            label="Energy"
            value={`${(report?.total_energy_kwh ?? 0).toFixed(3)}`}
            unit="kWh"
          />
          <Summary
            label="Cost"
            value={formatCurrency(report?.total_cost_inr ?? 0, symbol)}
          />
          <Summary
            label="Peak"
            value={`${(report?.peak_power_w ?? 0).toFixed(0)}`}
            unit="W"
          />
          <Summary
            label="Average"
            value={`${(report?.average_power_w ?? 0).toFixed(0)}`}
            unit="W"
          />
        </div>

        {/* --- hourly consumption --- */}
        {hourly.length > 0 ? (
          <div>
            <span className="label-muted">Consumption by hour</span>
            <div className="mt-1.5 h-[130px]">
              <Bar data={chart} options={barOptions("Wh")} />
            </div>
          </div>
        ) : null}

        {/* --- appliance table --- */}
        <div>
          <span className="label-muted">Appliance breakdown</span>
          <ScrollArea className="mt-1.5 max-h-[200px]">
            <table className="w-full text-[0.68rem]">
              <thead className="sticky top-0 bg-card/95 text-muted-foreground backdrop-blur">
                <tr className="border-b border-border/60">
                  <th className="py-1.5 text-left font-medium">Appliance</th>
                  <th className="py-1.5 text-right font-medium">kWh</th>
                  <th className="py-1.5 text-right font-medium">Cost</th>
                  <th className="py-1.5 text-right font-medium">Runtime</th>
                  <th className="py-1.5 text-right font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {report?.appliances.length ? (
                  report.appliances.map((row) => (
                    <tr
                      key={row.appliance_id}
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
                        {row.energy_kwh.toFixed(4)}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {formatCurrency(row.cost_inr, symbol)}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                        {formatDuration(row.runtime_s)}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">
                        {(row.share * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={5}
                      className="py-6 text-center text-muted-foreground"
                    >
                      {loading ? "Building report…" : "No data for this period yet"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </ScrollArea>
        </div>

        {/* --- exports --- */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" asChild>
            <a href={api.reportDownloadUrl(period, "csv")} download>
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Export CSV
            </a>
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={api.reportDownloadUrl(period, "pdf")} download>
              <Download className="h-3.5 w-3.5" />
              Export PDF
            </a>
          </Button>
          {report?.start ? (
            <Badge variant="outline" className="ml-auto">
              {new Date(report.start).toLocaleString("en-GB", {
                day: "2-digit",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              })}
              {" → "}
              {report.end
                ? new Date(report.end).toLocaleString("en-GB", {
                    day: "2-digit",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : ""}
            </Badge>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function Summary({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="rounded-lg border border-border/50 bg-secondary/30 px-2.5 py-2">
      <p className="text-[0.62rem] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-0.5 font-mono text-sm font-semibold tabular-nums">
        {value}
        {unit ? (
          <span className="ml-1 text-[0.65rem] font-normal text-muted-foreground">
            {unit}
          </span>
        ) : null}
      </p>
    </div>
  );
}
