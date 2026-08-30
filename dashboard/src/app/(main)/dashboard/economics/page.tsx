import { format } from "date-fns";
import { Download, RotateCw, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { CostBreakdown } from "./_components/cost-breakdown";
import { GpuWallet } from "./_components/gpu-wallet";
import { OverviewKpis } from "./_components/overview-kpis";
import { RecoveryCurveCard } from "./_components/recovery-curve-card";
import { UpcomingCharges } from "./_components/upcoming-charges";
import { WasteDistributionCard } from "./_components/waste-distribution-card";

export default function Page() {
  const formattedDate = format(new Date("2026-08-30"), "EEEE, do MMMM yyyy");

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1">
        <h1 className="text-3xl tracking-tight">GPU Economics</h1>
        <p className="text-muted-foreground text-sm">{formattedDate}</p>
      </div>

      <Tabs defaultValue="dashboard" className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <TabsList variant="line">
            <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
            <TabsTrigger value="allocations">Allocations</TabsTrigger>
            <TabsTrigger value="transactions">Transactions</TabsTrigger>
          </TabsList>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 text-muted-foreground text-xs">
              <RotateCw className="size-4" />
              <span>Updated 5 min ago</span>
            </div>
            <Button size="sm" variant="outline">
              <Settings2 />Settings
            </Button>
            <Button size="sm" variant="outline">
              <Download data-icon="inline-start" />Export
            </Button>
          </div>
        </div>

        <TabsContent value="dashboard" className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <div className="xl:col-span-6">
              <OverviewKpis />
            </div>
            <div className="flex flex-col gap-4 xl:col-span-6">
              <CostBreakdown />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <div className="xl:col-span-7">
              <RecoveryCurveCard />
            </div>
            <div className="xl:col-span-5">
              <WasteDistributionCard />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <div className="xl:col-span-4">
              <GpuWallet />
            </div>
            <div className="xl:col-span-4">
              <UpcomingCharges />
            </div>
            <div className="xl:col-span-4">
              <div className="flex h-full min-h-48 items-center justify-center rounded-xl border border-border border-dashed text-muted-foreground text-sm">
                Quick actions coming soon
              </div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="allocations">
          <div className="flex h-64 items-center justify-center rounded-xl border border-border border-dashed text-muted-foreground">
            Allocation detail coming soon.
          </div>
        </TabsContent>

        <TabsContent value="transactions">
          <div className="flex h-64 items-center justify-center rounded-xl border border-border border-dashed text-muted-foreground">
            Transaction history coming soon.
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
