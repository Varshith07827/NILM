import { Cpu } from "lucide-react";
import { useMemo } from "react";

import { AccuracyPanel } from "@/components/AccuracyPanel";
import { EventTimeline } from "@/components/EventTimeline";
import { NotificationPanel } from "@/components/NotificationPanel";
import { PageHeader } from "@/components/layout/PageHeader";
import { useLive } from "@/state/live";

export default function Diagnostics() {
  const { frame, status, alerts, events } = useLive();

  const applianceIcons = useMemo(() => {
    const map: Record<string, { icon: string; colour: string }> = {};
    for (const appliance of frame?.appliances ?? []) {
      map[appliance.id] = { icon: appliance.icon, colour: appliance.colour };
    }
    return map;
  }, [frame?.appliances]);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={Cpu}
        title="Diagnostics"
        description="How well the detector is doing right now, what it is running on, and everything that has happened in the house."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <AccuracyPanel frame={frame} model={status?.model ?? null} />
        <NotificationPanel alerts={alerts} />
        <EventTimeline events={events} applianceIcons={applianceIcons} />
      </div>
    </div>
  );
}
