import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Info,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, formatClock } from "@/lib/utils";
import type { Alert, AlertLevel } from "@/types";

const LEVEL_STYLE: Record<
  AlertLevel,
  { icon: typeof Info; ring: string; text: string; bg: string }
> = {
  info: {
    icon: Info,
    ring: "border-primary/25",
    text: "text-primary",
    bg: "bg-primary/10",
  },
  success: {
    icon: CheckCircle2,
    ring: "border-success/25",
    text: "text-success",
    bg: "bg-success/10",
  },
  warning: {
    icon: AlertTriangle,
    ring: "border-warning/25",
    text: "text-warning",
    bg: "bg-warning/10",
  },
  critical: {
    icon: ShieldAlert,
    ring: "border-destructive/30",
    text: "text-destructive",
    bg: "bg-destructive/10",
  },
};

export function NotificationPanel({ alerts }: { alerts: Alert[] }) {
  const critical = alerts.filter((a) => a.level === "critical").length;
  const warnings = alerts.filter((a) => a.level === "warning").length;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>
          <Bell className="h-3.5 w-3.5 text-primary" />
          Notifications
        </CardTitle>
        <div className="flex items-center gap-1">
          {critical > 0 ? (
            <Badge variant="destructive">{critical} critical</Badge>
          ) : null}
          {warnings > 0 ? (
            <Badge variant="warning">{warnings} warning</Badge>
          ) : null}
          {critical === 0 && warnings === 0 ? (
            <Badge variant="outline">{alerts.length}</Badge>
          ) : null}
        </div>
      </CardHeader>

      <CardContent>
        <ScrollArea className="h-[300px]">
          {alerts.length === 0 ? (
            <div className="flex h-[280px] flex-col items-center justify-center gap-2 text-muted-foreground">
              <CheckCircle2 className="h-6 w-6 opacity-40" />
              <p className="text-xs">Nothing needs your attention</p>
            </div>
          ) : (
            <div className="space-y-1.5 pr-2">
              {alerts.map((alert, index) => {
                const style = LEVEL_STYLE[alert.level];
                const Icon = style.icon;
                return (
                  <div
                    key={`${alert.sim_time}-${alert.title}-${index}`}
                    className={cn(
                      "flex gap-2.5 rounded-lg border p-2.5 animate-fade-in",
                      style.ring,
                      style.bg,
                    )}
                  >
                    <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", style.text)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <p className={cn("text-xs font-semibold", style.text)}>
                          {alert.title}
                        </p>
                        <span className="shrink-0 font-mono text-[0.62rem] tabular-nums text-muted-foreground">
                          {formatClock(alert.sim_time)}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[0.7rem] leading-relaxed text-muted-foreground">
                        {alert.message}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
