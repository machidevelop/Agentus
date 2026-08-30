import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function OverviewKpis() {
  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10">
      <div className="grid grid-cols-1 xl:grid-cols-8">
        <Card className="gap-5 overflow-hidden rounded-none border-0 border-foreground/10 border-b ring-0 xl:col-span-4 xl:border-r">
          <CardHeader>
            <CardTitle className="font-normal">GPU Cluster Value</CardTitle>
          </CardHeader>
          <CardContent className="flex items-end justify-between">
            <div className="space-y-1">
              <div className="text-3xl leading-none tracking-tight">$48.2M</div>
              <p className="text-muted-foreground text-xs">+$6.4M vs last quarter</p>
            </div>
            <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">+15.3%</Badge>
          </CardContent>
        </Card>

        <Card className="gap-5 overflow-hidden rounded-none border-0 border-foreground/10 border-b ring-0 xl:col-span-4">
          <CardHeader>
            <CardTitle className="font-normal">Recoverable / Month</CardTitle>
          </CardHeader>
          <CardContent className="flex items-end justify-between">
            <div className="flex flex-col gap-1">
              <div className="text-3xl leading-none tracking-tight">$535k</div>
              <p className="text-muted-foreground text-xs">$59k above last month average</p>
            </div>
            <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">+12.4%</Badge>
          </CardContent>
        </Card>

        <Card className="gap-5 overflow-hidden rounded-none border-0 border-foreground/10 ring-0 xl:col-span-4 xl:border-r">
          <CardHeader>
            <CardTitle className="font-normal">GPU Cost / Month</CardTitle>
          </CardHeader>
          <CardContent className="flex items-end justify-between">
            <div className="flex flex-col gap-1">
              <div className="text-3xl leading-none tracking-tight">$1.24M</div>
              <p className="text-muted-foreground text-xs">$84k more than last month</p>
            </div>
            <Badge variant="destructive" className="bg-destructive/10 text-destructive">+7.3%</Badge>
          </CardContent>
        </Card>

        <Card className="gap-5 overflow-hidden rounded-none border-0 ring-0 xl:col-span-4">
          <CardHeader>
            <CardTitle className="font-normal">Utilization Rate</CardTitle>
          </CardHeader>
          <CardContent className="flex items-end justify-between">
            <div className="flex flex-col gap-1">
              <div className="text-3xl leading-none tracking-tight">61.3%</div>
              <p className="text-muted-foreground text-xs">Down from 63.4% last week</p>
            </div>
            <Badge variant="destructive" className="bg-destructive/10 text-destructive">-2.1%</Badge>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
