import { ArrowDownRight, ArrowUpRight, Ellipsis } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function KpiStrip() {
  return (
    <div className="overflow-hidden rounded-xl bg-card shadow-xs ring-1 ring-foreground/10">
      <div className="grid divide-y *:data-[slot=card]:rounded-none *:data-[slot=card]:ring-0 md:grid-cols-2 md:divide-x md:divide-y-0 xl:grid-cols-5">
        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Total Findings</CardTitle>
            <CardAction>
              <Ellipsis className="size-4" />
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">5,524</div>
              <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">
                <ArrowUpRight />
                +116.0%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">2,558</span></span>
              <span>•</span>
              <span>5k run</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">High Confidence</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">4,969</div>
              <Badge className="bg-green-500/10 text-green-700 dark:bg-green-500/15 dark:text-green-300">
                <ArrowUpRight />+99.4%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">2,492</span></span>
              <span>•</span><span>5k run</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Monthly Value (5k)</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">$535k</div>
              <Badge className="bg-destructive/10 text-destructive">
                <ArrowDownRight />-47.3%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">$1.01M</span></span>
              <span>•</span><span>naive estimate</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Util Recovery</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">51.01%</div>
              <Badge className="bg-destructive/10 text-destructive">
                <ArrowDownRight />-8.24pp
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">59.25%</span></span>
              <span>•</span><span>5k run</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-normal text-sm">Avg Confidence</CardTitle>
            <CardAction><Ellipsis className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div className="text-2xl leading-none tracking-tight">0.842</div>
              <Badge className="bg-destructive/10 text-destructive">
                <ArrowDownRight />-1.7%
              </Badge>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <span>from <span className="text-foreground">0.857</span></span>
              <span>•</span><span>5k run</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
