import { LineChart } from "lucide-react";

import { LiveCharts } from "@/components/LiveCharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { useLive } from "@/state/live";

export default function LiveChartsPage() {
  const { history } = useLive();
  return (
    <div className="space-y-4">
      <PageHeader
        icon={LineChart}
        title="Live Charts"
        description="Current, voltage, power and power factor at the mains, streamed one window per simulated second."
      />
      <LiveCharts history={history} window={320} />
    </div>
  );
}
