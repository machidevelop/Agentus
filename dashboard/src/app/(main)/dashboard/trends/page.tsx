import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { AnalyticsTrendToolbar } from "./_components/analytics-trend-toolbar";
import { RealtimeGpuLoad } from "./_components/realtime-gpu-load";
import { TopClusters } from "./_components/top-clusters";
import { TopFindingTypes } from "./_components/top-finding-types";
import { TrendKpiStrip } from "./_components/trend-kpi-strip";
import { UtilizationQuality } from "./_components/utilization-quality";

export default function Page() {
  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1">
        <h1 className="text-3xl tracking-tight">GPU Infrastructure Trends</h1>
        <p className="text-muted-foreground text-sm">
          Monitor utilization, efficiency, and finding trends across all clusters.
        </p>
      </div>

      <Tabs defaultValue="overview" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList className="gap-1">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="clusters">Clusters</TabsTrigger>
            <TabsTrigger value="jobs">Jobs</TabsTrigger>
            <TabsTrigger value="efficiency">Efficiency</TabsTrigger>
            <TabsTrigger value="cost">Cost</TabsTrigger>
          </TabsList>
          <AnalyticsTrendToolbar />
        </div>

        <TabsContent value="overview" className="flex flex-col gap-4">
          <TrendKpiStrip />

          <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-12">
            <div className="xl:col-span-7">
              <UtilizationQuality />
            </div>
            <div className="xl:col-span-5">
              <RealtimeGpuLoad />
            </div>
          </div>

          <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-12">
            <div className="xl:col-span-7">
              <TopClusters />
            </div>
            <div className="xl:col-span-5 xl:col-start-8">
              <TopFindingTypes />
            </div>
          </div>
        </TabsContent>

        {["clusters", "jobs", "efficiency", "cost"].map((tab) => (
          <TabsContent key={tab} value={tab}>
            <div className="flex h-64 items-center justify-center rounded-xl border border-border border-dashed text-muted-foreground capitalize">
              {tab} view coming soon.
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
