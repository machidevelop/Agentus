import { FindingsSection } from "./_components/findings-section";
import { KpiCards } from "./_components/kpi-cards";
import { PipelineActivity } from "./_components/pipeline-activity";

export default function Page() {
  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <KpiCards />
      <PipelineActivity />
      <FindingsSection />
    </div>
  );
}
