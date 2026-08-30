import { Server } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const clusters = [
  { id: 1, name: "aws-us-east-1", spec: "A100×256", costPerMonth: "$89,344/mo" },
  { id: 2, name: "gcp-europe-west4", spec: "H100×128", costPerMonth: "$104,192/mo" },
  { id: 3, name: "azure-eastus", spec: "A100×64", costPerMonth: "$22,336/mo" },
];

const reserves = [
  { id: 1, name: "On-Demand Pool", spec: "32 GPUs", costPerMonth: "$11,168/mo" },
  { id: 2, name: "Spot Reserve", spec: "16 GPUs", costPerMonth: "Unmetered" },
];

export function GpuWallet() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">GPU Clusters</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-4">
          {clusters.map((cluster) => (
            <div key={cluster.id} className="flex items-center justify-between">
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground text-sm leading-none">{cluster.name}</span>
                </div>
                <span className="font-normal text-muted-foreground text-xs">{cluster.spec} · {cluster.costPerMonth}</span>
              </div>
              <div className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-background">
                <Server className="size-4 text-muted-foreground" />
              </div>
            </div>
          ))}
        </div>

        <Separator />

        <div className="flex flex-col gap-4">
          {reserves.map((reserve) => (
            <div key={reserve.id} className="flex items-center justify-between">
              <div className="flex flex-col gap-0.5">
                <span className="font-medium text-foreground text-sm leading-none">{reserve.name}</span>
                <span className="font-normal text-muted-foreground text-xs">{reserve.spec} · {reserve.costPerMonth}</span>
              </div>
              <div className="flex size-9 shrink-0 items-center justify-center rounded-md border bg-background">
                <Server className="size-4 text-muted-foreground" />
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <span className="font-medium text-[10px] text-muted-foreground">Billing: <span className="text-foreground">Monthly cycle</span></span>
          <div className="flex items-center gap-1.5">
            <div className="size-1 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]" />
            <span className="font-bold text-[9px] text-green-500 uppercase tracking-widest">Active</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
