import { FindingsSummary } from "./_components/findings-summary";
import { MetricCards } from "./_components/metric-cards";
import { RecoveryOverview } from "./_components/recovery-overview";

export default function Page() {
  return (
    <div className="flex flex-col gap-6">
      <MetricCards />
      <RecoveryOverview />
      <FindingsSummary />
    </div>
  );
}
