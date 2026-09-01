import { ArrowUpRight, TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export function ClusterKpiCards() {
  return (
    <section className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-3xl tracking-tight">Cluster Overview</h2>
        <p className="text-muted-foreground text-sm">
          Real-time GPU allocation status, utilization health, and waste signals across the cluster.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Active GPUs</CardDescription>
            <CardAction>
              <ArrowUpRight className="size-4" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">0</span>
              <Badge
                variant="outline"
                className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300"
              >
                <TrendingUp />
                0
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">0</span>{" "}
              <span className="text-muted-foreground">active last scan</span>
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Idle GPUs</CardDescription>
            <CardAction>
              <ArrowUpRight className="size-4" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">0</span>
              <Badge variant="outline" className="border-destructive/20 bg-destructive/10 text-destructive">
                <TrendingDown />
                0
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">0</span>{" "}
              <span className="text-muted-foreground">idle last scan</span>
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Avg Utilization</CardDescription>
            <CardAction>
              <ArrowUpRight className="size-4" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">0%</span>
              <Badge
                variant="outline"
                className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300"
              >
                <TrendingUp />
                0
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">0%</span>{" "}
              <span className="text-muted-foreground">last week</span>
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardDescription>Waste Identified</CardDescription>
            <CardAction>
              <ArrowUpRight className="size-4" />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">$0</span>
              <Badge
                variant="outline"
                className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300"
              >
                <TrendingUp />
                $0
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">$0</span>{" "}
              <span className="text-muted-foreground">prev run</span>
            </p>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
