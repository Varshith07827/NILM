/**
 * Application shell: sidebar navigation, top bar, and the routed page outlet.
 *
 * The live numbers in the top bar are deliberately duplicated across every
 * page. When someone is looking at the billing page and the air conditioner
 * kicks in, they should see it without navigating away.
 */

import {
  Activity,
  BarChart3,
  Boxes,
  ChevronLeft,
  Cpu,
  FileText,
  Gauge,
  Home,
  LayoutDashboard,
  Moon,
  Radio,
  Receipt,
  Sun,
  WifiOff,
  Zap,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InfoTip } from "@/components/ui/tooltip";
import { useLive } from "@/state/live";
import { cn, formatClock, formatCurrency, formatPower } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Home;
  hint: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    to: "/",
    label: "Overview",
    icon: LayoutDashboard,
    hint: "Headline metrics and live measurement traces",
  },
  {
    to: "/home",
    label: "3D Home",
    icon: Home,
    hint: "Walk the house, click appliances to switch them",
  },
  {
    to: "/appliances",
    label: "Appliances",
    icon: Boxes,
    hint: "Per-appliance detection, confidence and power",
  },
  {
    to: "/analytics",
    label: "Analytics",
    icon: BarChart3,
    hint: "Raw waveform, harmonics and power quality",
  },
  {
    to: "/billing",
    label: "Billing",
    icon: Receipt,
    hint: "Cost, tariffs and slab breakdown",
  },
  {
    to: "/reports",
    label: "Reports",
    icon: FileText,
    hint: "Daily, weekly and monthly reports with export",
  },
  {
    to: "/diagnostics",
    label: "Diagnostics",
    icon: Cpu,
    hint: "Model card, detector accuracy, events and alerts",
  },
];

const MODE_LABEL: Record<string, string> = {
  demo: "Demo",
  simulation: "Simulation",
  replay: "Replay",
};

export function AppShell() {
  const { frame, status, connection, theme, toggleTheme, alerts } = useLive();
  const [collapsed, setCollapsed] = useState(false);

  const model = status?.model;
  const running = frame?.state === "running";
  const power = formatPower(frame?.measurement.power_w ?? 0);
  const unreadCritical = alerts.filter(
    (alert) => alert.level === "critical" || alert.level === "warning",
  ).length;

  return (
    <div className="flex min-h-screen">
      {/* ------------------------------------------------------------- */}
      {/* sidebar                                                        */}
      {/* ------------------------------------------------------------- */}
      <aside
        className={cn(
          "sticky top-0 z-40 flex h-screen shrink-0 flex-col border-r border-white/[0.06] bg-card/40 backdrop-blur-xl transition-[width] duration-200",
          collapsed ? "w-[68px]" : "w-[232px]",
        )}
      >
        <div className="flex h-16 items-center gap-2.5 px-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/25 to-accent/25 ring-1 ring-inset ring-white/10">
            <Zap className="h-4.5 w-4.5 text-primary" />
          </div>
          {!collapsed ? (
            <div className="min-w-0 leading-tight">
              <p className="truncate text-[13px] font-bold tracking-tight">
                Edge AI <span className="text-gradient">NILM</span>
              </p>
              <p className="truncate text-[0.64rem] text-muted-foreground">
                Smart Energy Monitor
              </p>
            </div>
          ) : null}
        </div>

        <nav className="flex-1 space-y-1 px-2.5 py-3">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const link = (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs font-medium transition-colors",
                    isActive
                      ? "bg-primary/12 text-primary"
                      : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                    collapsed && "justify-center px-0",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive ? (
                      <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary" />
                    ) : null}
                    <Icon className="h-4 w-4 shrink-0" />
                    {!collapsed ? <span>{item.label}</span> : null}
                    {!collapsed && item.to === "/diagnostics" && unreadCritical ? (
                      <span className="ml-auto rounded bg-warning/20 px-1.5 text-[0.6rem] font-semibold text-warning">
                        {unreadCritical}
                      </span>
                    ) : null}
                  </>
                )}
              </NavLink>
            );

            return collapsed ? (
              <InfoTip key={item.to} label={item.label} side="right">
                <div>{link}</div>
              </InfoTip>
            ) : (
              <InfoTip key={item.to} label={item.hint} side="right">
                <div>{link}</div>
              </InfoTip>
            );
          })}
        </nav>

        {/* model summary at the foot of the rail */}
        {!collapsed && model ? (
          <div className="mx-2.5 mb-2 rounded-lg border border-border/50 bg-secondary/30 p-2.5">
            <p className="label-muted">Inference</p>
            <p className="mt-1 truncate font-mono text-[0.68rem] font-medium">
              {model.model_available ? model.architecture : "harmonic baseline"}
            </p>
            <div className="mt-1 flex items-center justify-between text-[0.64rem] text-muted-foreground">
              <span>{model.backend}</span>
              <span className="font-mono">
                {(frame?.inference?.median_latency_ms ?? 0).toFixed(1)} ms
              </span>
            </div>
          </div>
        ) : null}

        <div className="border-t border-white/[0.05] p-2.5">
          <Button
            variant="ghost"
            size="sm"
            className={cn("w-full", collapsed && "px-0")}
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <ChevronLeft
              className={cn(
                "h-4 w-4 transition-transform",
                collapsed && "rotate-180",
              )}
            />
            {!collapsed ? <span>Collapse</span> : null}
          </Button>
        </div>
      </aside>

      {/* ------------------------------------------------------------- */}
      {/* main column                                                    */}
      {/* ------------------------------------------------------------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-background/70 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
            {/* simulated clock */}
            <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-secondary/40 px-3 py-1.5">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  running ? "live-dot" : "bg-muted-foreground",
                )}
              />
              <span className="font-mono text-sm font-semibold tabular-nums">
                {frame ? formatClock(frame.sim_time) : "--:--:--"}
              </span>
              <span className="hidden text-[0.62rem] uppercase tracking-wider text-muted-foreground sm:inline">
                sim
              </span>
            </div>

            {/* live power, always visible whatever page you are on */}
            <div className="hidden items-baseline gap-1.5 rounded-lg border border-primary/20 bg-primary/10 px-3 py-1.5 md:flex">
              <span className="font-mono text-sm font-bold tabular-nums text-primary">
                {power.value}
              </span>
              <span className="text-[0.65rem] text-primary/70">{power.unit}</span>
            </div>

            {frame ? (
              <div className="hidden items-baseline gap-1.5 rounded-lg border border-border/60 bg-secondary/40 px-3 py-1.5 lg:flex">
                <span className="font-mono text-sm font-semibold tabular-nums">
                  {formatCurrency(
                    frame.cost.today_inr,
                    frame.cost.currency_symbol,
                  )}
                </span>
                <span className="text-[0.62rem] text-muted-foreground">today</span>
              </div>
            ) : null}

            <div className="flex-1" />

            {frame ? (
              <Badge
                variant={
                  frame.mode === "demo"
                    ? "default"
                    : frame.mode === "replay"
                      ? "accent"
                      : "success"
                }
                className="hidden sm:inline-flex"
              >
                <Radio className="h-3 w-3" />
                {MODE_LABEL[frame.mode]} · {frame.speed}x
              </Badge>
            ) : null}

            {frame ? (
              <InfoTip label="Live F1 of the detector against the simulator's hidden ground truth">
                <Badge variant="secondary" className="hidden cursor-help lg:inline-flex">
                  <Gauge className="h-3 w-3" />
                  F1 {(frame.accuracy.f1 * 100).toFixed(1)}%
                </Badge>
              </InfoTip>
            ) : null}

            <InfoTip
              label={
                connection === "open"
                  ? "Streaming live over WebSocket"
                  : connection === "connecting"
                    ? "Connecting to the backend…"
                    : "Disconnected. Retrying automatically."
              }
            >
              <Badge
                variant={
                  connection === "open"
                    ? "success"
                    : connection === "connecting"
                      ? "warning"
                      : "destructive"
                }
                className="cursor-help"
              >
                {connection === "closed" ? (
                  <WifiOff className="h-3 w-3" />
                ) : (
                  <Activity className="h-3 w-3" />
                )}
                <span className="hidden sm:inline">
                  {connection === "open" ? "Live" : connection}
                </span>
              </Badge>
            </InfoTip>

            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              aria-label="Toggle colour theme"
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
              )}
            </Button>
          </div>
        </header>

        <main className="flex-1 px-4 py-5 sm:px-6">
          <Outlet />
        </main>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 px-4 py-4 text-[0.68rem] text-muted-foreground sm:px-6">
          <p>
            Edge AI-Based Non-Intrusive Load Monitoring — appliance figures are
            estimates produced by disaggregating a single mains measurement, not
            sub-metered readings.
          </p>
          {status ? (
            <p className="font-mono">
              {(status.stats?.windows_processed ?? 0).toLocaleString()} windows ·{" "}
              {(status.stats?.loop_ms_median ?? 0).toFixed(1)} ms/window
            </p>
          ) : null}
        </footer>
      </div>
    </div>
  );
}
