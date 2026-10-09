import { SlidersHorizontal } from "lucide-react";

import { SimulationControls } from "@/components/SimulationControls";
import { PageHeader } from "@/components/layout/PageHeader";
import { useLive } from "@/state/live";

export default function ControlPage() {
  const { status, scenarios, onChanged } = useLive();
  return (
    <div className="space-y-4">
      <PageHeader
        icon={SlidersHorizontal}
        title="Simulation Control"
        description="Start, pause and reset the virtual house, pick a scenario and speed, and record or replay runs."
      />
      <div className="max-w-xl">
        <SimulationControls status={status} scenarios={scenarios} onChanged={onChanged} />
      </div>
    </div>
  );
}
