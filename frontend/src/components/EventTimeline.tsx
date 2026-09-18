import { History, Power, PowerOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { InfoTip } from "@/components/ui/tooltip";
import { applianceIcon } from "@/lib/icons";
import { cn, formatClock } from "@/lib/utils";
import type { ApplianceEvent } from "@/types";

const SOURCE_LABEL: Record<string, string> = {
  script: "scripted",
  autonomous: "auto",
  manual: "manual",
  scenario: "preset",
  replay: "replay",
};

const SOURCE_HELP: Record<string, string> = {
  script: "Fired by the demo timeline for this scenario",
  autonomous: "The appliance decided to switch on by itself",
  manual: "You switched this from the dashboard",
  scenario: "Set as part of the scenario's starting state",
  replay: "Reproduced from a saved recording",
};

function IconFor({ name }: { name: string }) {
  const Icon = applianceIcon(name);
  return <Icon className="h-3 w-3" />;
}

export function EventTimeline({
  events,
  applianceIcons,
}: {
  events: ApplianceEvent[];
  applianceIcons: Record<string, { icon: string; colour: string }>;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>
          <History className="h-3.5 w-3.5 text-primary" />
          Event Timeline
        </CardTitle>
        <Badge variant="outline">{events.length}</Badge>
      </CardHeader>

      <CardContent>
        <ScrollArea className="h-[300px]">
          {events.length === 0 ? (
            <div className="flex h-[280px] items-center justify-center text-xs text-muted-foreground">
              No switching events yet
            </div>
          ) : (
            <ol className="relative space-y-0 pr-2">
              {/* the spine */}
              <div
                aria-hidden
                className="absolute bottom-2 left-[0.9rem] top-2 w-px bg-border"
              />
              {events.map((event, index) => {
                const meta = applianceIcons[event.appliance_id];
                const isOn = event.action === "on";
                return (
                  <li
                    key={`${event.timestamp}-${event.appliance_id}-${index}`}
                    className="relative flex gap-3 py-1.5 animate-slide-in-left"
                  >
                    <span
                      className={cn(
                        "relative z-10 mt-0.5 flex h-[1.8rem] w-[1.8rem] shrink-0 items-center justify-center rounded-full border-2 border-background",
                      )}
                      style={{
                        background: isOn
                          ? `${meta?.colour ?? "#38bdf8"}26`
                          : "hsl(var(--secondary))",
                        color: isOn
                          ? (meta?.colour ?? "#38bdf8")
                          : "hsl(var(--muted-foreground))",
                      }}
                    >
                      {meta ? (
                        <IconFor name={meta.icon} />
                      ) : isOn ? (
                        <Power className="h-3 w-3" />
                      ) : (
                        <PowerOff className="h-3 w-3" />
                      )}
                    </span>

                    <div className="min-w-0 flex-1 pb-1">
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-[0.68rem] tabular-nums text-muted-foreground">
                          {formatClock(event.timestamp)}
                        </span>
                        <span className="truncate text-xs font-medium">
                          {event.appliance_name}
                        </span>
                        <Badge
                          variant={isOn ? "success" : "outline"}
                          className="ml-auto shrink-0 px-1.5 py-0"
                        >
                          {isOn ? "ON" : "OFF"}
                        </Badge>
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        {event.note ? (
                          <span className="truncate text-[0.68rem] text-muted-foreground">
                            {event.note}
                          </span>
                        ) : null}
                        <InfoTip
                          label={SOURCE_HELP[event.source] ?? event.source}
                        >
                          <span className="ml-auto shrink-0 cursor-help rounded border border-border/60 px-1 text-[0.6rem] uppercase tracking-wide text-muted-foreground">
                            {SOURCE_LABEL[event.source] ?? event.source}
                          </span>
                        </InfoTip>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
