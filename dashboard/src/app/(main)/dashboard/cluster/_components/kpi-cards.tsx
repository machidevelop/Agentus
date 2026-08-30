import { ArrowUpRight, TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export function KpiCards() {
  return (
    <section className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-3xl tracking-tight">Cluster Overview</h2>
        <p className="text-muted-foreground text-sm">
          GPU infrastructure topology, utilization, and job distribution across all registered clusters.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Total GPUs</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">512</span>
              <Badge variant="outline" className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300">
                <TrendingUp />+64
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">448</span>{" "}
              <span className="text-muted-foreground">last quarter</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Active Jobs</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">127</span>
              <Badge variant="outline" className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300">
                <TrendingUp />+3
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">124</span>{" "}
              <span className="text-muted-foreground">1 hour ago</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Mean Utilization</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">61.3%</span>
              <Badge variant="outline" className="border-destructive/20 bg-destructive/10 text-destructive">
                <TrendingDown />-2.1%
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">63.4%</span>{" "}
              <span className="text-muted-foreground">last week</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Idle GPUs</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">198</span>
              <Badge variant="outline" className="border-destructive/20 bg-destructive/10 text-destructive">
                <TrendingDown />38.7%
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">512</span>{" "}
              <span className="text-muted-foreground">total GPUs</span>
            </p>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
