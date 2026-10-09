import { PieChart } from "lucide-react";

import { EnergyBreakdown } from "@/components/EnergyBreakdown";
import { PageHeader } from "@/components/layout/PageHeader";
import { useLive } from "@/state/live";

export default function BreakdownPage() {
  const { frame } = useLive();
  return (
    <div className="space-y-4">
      <PageHeader
        icon={PieChart}
        title="Energy Breakdown"
        description="How the metered power splits across devices right now, including the share the model could not attribute."
      />
      <EnergyBreakdown frame={frame} />
    </div>
  );
}
