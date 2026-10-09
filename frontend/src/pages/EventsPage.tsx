import { History } from "lucide-react";
import { useMemo } from "react";

import { EventTimeline } from "@/components/EventTimeline";
import { PageHeader } from "@/components/layout/PageHeader";
import { useLive } from "@/state/live";

export default function EventsPage() {
  const { frame, events } = useLive();

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
        icon={History}
        title="Events"
        description="Every switch-on and switch-off in the house, and whether the detector picked it up."
      />
      <div className="max-w-3xl">
        <EventTimeline events={events} applianceIcons={applianceIcons} />
      </div>
    </div>
  );
}
