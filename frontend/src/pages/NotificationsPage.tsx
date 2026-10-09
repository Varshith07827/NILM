import { Bell, BellOff, CheckCheck, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/PageHeader";
import { api } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import { useNotifications, type PopupLevel } from "@/state/notifications";
import type { AlertLevel, NotificationItem } from "@/types";

const PAGE_SIZE = 40;

const LEVEL_STYLE: Record<AlertLevel, string> = {
  critical: "border-l-destructive",
  warning: "border-l-warning",
  success: "border-l-success",
  info: "border-l-primary",
};

const LEVEL_BADGE: Record<AlertLevel, "destructive" | "warning" | "success" | "secondary"> = {
  critical: "destructive",
  warning: "warning",
  success: "success",
  info: "secondary",
};

export default function NotificationsPage() {
  const { unread, markRead, popupLevel, setPopupLevel, permission, version } =
    useNotifications();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(PAGE_SIZE);

  const load = useCallback(async () => {
    try {
      const page = await api.notifications({ limit, unreadOnly });
      setItems(page.items);
      setTotal(unreadOnly ? page.unread : page.total);
    } catch {
      /* the list stays as it was; the bell keeps retrying */
    } finally {
      setLoading(false);
    }
  }, [limit, unreadOnly]);

  // Reload whenever a new alert arrives or something is marked read.
  useEffect(() => {
    void load();
  }, [load, version]);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Bell}
        title="Notifications"
        description="Every alert the house has raised: load limits, current surges, budget, appliances left running. Kept until you clear them."
        actions={
          <Button
            size="sm"
            variant="outline"
            disabled={!unread}
            onClick={() => void markRead()}
          >
            <CheckCheck className="h-3.5 w-3.5" />
            Mark all read
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-8">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle>
              <Bell className="h-3.5 w-3.5 text-primary" />
              {unread} unread
            </CardTitle>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant={unreadOnly ? "outline" : "default"}
                onClick={() => setUnreadOnly(false)}
              >
                All
              </Button>
              <Button
                size="sm"
                variant={unreadOnly ? "default" : "outline"}
                onClick={() => setUnreadOnly(true)}
              >
                Unread
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {loading ? (
              <div className="flex justify-center py-8 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : items.length === 0 ? (
              <p className="py-8 text-center text-xs text-muted-foreground">
                {unreadOnly ? "Nothing unread." : "No notifications yet."}
              </p>
            ) : (
              items.map((item) => (
                <div
                  key={item.id}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border border-l-[3px] border-border/50 px-3 py-2.5",
                    LEVEL_STYLE[item.level],
                    item.read ? "opacity-60" : "bg-secondary/30",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-xs font-semibold">{item.title}</p>
                      <Badge variant={LEVEL_BADGE[item.level]}>{item.level}</Badge>
                      <span className="text-[0.62rem] text-muted-foreground">
                        {item.category} · sim {formatDateTime(item.sim_time)}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[0.7rem] leading-relaxed text-muted-foreground">
                      {item.message}
                    </p>
                  </div>
                  {!item.read ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void markRead([item.id])}
                    >
                      Mark read
                    </Button>
                  ) : null}
                </div>
              ))
            )}
            {items.length < total ? (
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => setLimit((value) => value + PAGE_SIZE)}
              >
                Show more ({total - items.length} older)
              </Button>
            ) : null}
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader className="pb-3">
            <CardTitle>
              {popupLevel === "off" ? (
                <BellOff className="h-3.5 w-3.5 text-primary" />
              ) : (
                <Bell className="h-3.5 w-3.5 text-primary" />
              )}
              Desktop pop-ups
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-[0.7rem] text-muted-foreground">
            <p className="leading-relaxed">
              Show alerts as system notifications while this dashboard is open,
              even in a background tab. This browser only; nothing is sent
              anywhere else.
            </p>
            <Select
              value={popupLevel}
              disabled={permission === "unsupported"}
              onValueChange={(value) => void setPopupLevel(value as PopupLevel)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="off">Off</SelectItem>
                <SelectItem value="important">Warnings and critical only</SelectItem>
                <SelectItem value="all">Every alert</SelectItem>
              </SelectContent>
            </Select>
            {permission === "denied" ? (
              <p className="text-warning">
                The browser is blocking notifications for this site. Allow them in
                the site settings (the icon beside the address bar), then choose
                again here.
              </p>
            ) : null}
            {permission === "unsupported" ? (
              <p className="text-warning">This browser does not support notifications.</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
