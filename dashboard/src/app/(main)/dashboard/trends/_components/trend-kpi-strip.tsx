import { ArrowDownRight, ArrowUpRight, Ellipsis } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function TrendKpiStrip() {
  return (
    <div className="overflow-hidden rounded-xl bg-card shadow-xs ring-1 ring-foreground/10">
      <div className="grid divide-y *:data-[slot=card]:rounded-none *:data-[slot=card]:ring-0 md:grid-cols-2 md:divide-x md:divide-y-0 xl:grid-cols-5">
        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">GPU Utilization</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">61.3%</div>
              <Badge className="bg-destructive/10 text-destructive">
                <ArrowDownRight />2.1%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">63.4%</span></span>
              <span>•</span>
              <span>last 4 weeks</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Findings / Day</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">85.3</div>
              <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">
                <ArrowUpRight />12.4%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">75.9</span></span>
              <span>•</span>
              <span>last 4 weeks</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Queue Wait Avg</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">802 min</div>
              <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">
                <ArrowDownRight />6.7%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">860 min</span></span>
              <span>•</span>
              <span>last 4 weeks</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Recovery Rate</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">43.2%</div>
              <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">
                <ArrowUpRight />8.1%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">39.9%</span></span>
              <span>•</span>
              <span>last 4 weeks</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Cluster Efficiency</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">74.5%</div>
              <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">
                <ArrowUpRight />1.8%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">73.2%</span></span>
              <span>•</span>
              <span>last 4 weeks</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
