import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const clusters = [
  {
    name: "aws-us-east-1",
    gpus: 256,
    model: "A100-80GB",
    activeJobs: 68,
    utilization: 73,
    findings: 1284,
    color: "bg-sky-500",
    lightColor: "bg-sky-500/12",
  },
  {
    name: "gcp-europe-west4",
    gpus: 128,
    model: "H100-SXM5",
    activeJobs: 34,
    utilization: 58,
    findings: 621,
    color: "bg-violet-500",
    lightColor: "bg-violet-500/12",
  },
  {
    name: "azure-eastus",
    gpus: 64,
    model: "A100-80GB",
    activeJobs: 18,
    utilization: 81,
    findings: 412,
    color: "bg-emerald-500",
    lightColor: "bg-emerald-500/12",
  },
  {
    name: "on-prem-dc1",
    gpus: 64,
    model: "A100-40GB",
    activeJobs: 7,
    utilization: 42,
    findings: 241,
    color: "bg-amber-500",
    lightColor: "bg-amber-500/12",
  },
];

export function ClusterTopologyCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cluster Topology</CardTitle>
        <CardAction>
          <Select defaultValue="all">
            <SelectTrigger size="sm" className="min-w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">All clusters</SelectItem>
                <SelectItem value="aws">AWS</SelectItem>
                <SelectItem value="gcp">GCP</SelectItem>
                <SelectItem value="azure">Azure</SelectItem>
                <SelectItem value="onprem">On-prem</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 lg:grid-cols-4">
          {clusters.map((cluster) => (
            <div key={cluster.name} className={`flex flex-col gap-4 rounded-xl p-4 ${cluster.lightColor}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold text-sm">{cluster.name}</div>
                  <div className="text-muted-foreground text-xs">{cluster.model}</div>
                </div>
                <div className={`h-2.5 w-2.5 rounded-full ${cluster.color} mt-1`} />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-0.5">
                  <span className="text-muted-foreground text-[11px] uppercase tracking-wider">GPUs</span>
                  <span className="font-bold text-2xl tabular-nums leading-none">{cluster.gpus}</span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-muted-foreground text-[11px] uppercase tracking-wider">Jobs</span>
                  <span className="font-bold text-2xl tabular-nums leading-none">{cluster.activeJobs}</span>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground text-xs">Utilization</span>
                  <span className="font-medium text-sm tabular-nums">{cluster.utilization}%</span>
                </div>
                <Progress
                  value={cluster.utilization}
                  className={`h-2 ${cluster.lightColor} *:data-[slot='progress-indicator']:${cluster.color}`}
                />
              </div>

              <div className="flex items-center justify-between rounded-lg border border-border/50 px-3 py-2">
                <span className="text-muted-foreground text-xs">Findings</span>
                <span className="font-semibold text-sm tabular-nums">{cluster.findings.toLocaleString()}</span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
