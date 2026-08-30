import { ClusterNodesSection } from "./_components/cluster-nodes-section";
import { ClusterTopologyCard } from "./_components/cluster-topology-card";
import { KpiCards } from "./_components/kpi-cards";

export default function Page() {
  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <KpiCards />
      <ClusterTopologyCard />
      <ClusterNodesSection />
    </div>
  );
}
