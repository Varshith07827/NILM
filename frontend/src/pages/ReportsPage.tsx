import { FileText } from "lucide-react";

import { ReportsPanel } from "@/components/ReportsPanel";
import { PageHeader } from "@/components/layout/PageHeader";

export default function ReportsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        icon={FileText}
        title="Reports"
        description="Daily, weekly and monthly consumption built from the hourly energy buckets, exportable to CSV and PDF."
      />
      <ReportsPanel />
    </div>
  );
}
