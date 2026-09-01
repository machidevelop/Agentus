import { ArrowUpRight, TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

export function KpiCards() {
  return (
    <section className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-3xl tracking-tight">Findings Overview</h2>
        <p className="text-muted-foreground text-sm">
          GPU waste findings detected across all clusters — confidence scores, recovery potential, and review status.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Total Findings</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">0</span>
              <Badge variant="outline" className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300">
                <TrendingUp />0%
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">0</span>{" "}
              <span className="text-muted-foreground">last month</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>High Confidence</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">0</span>
              <Badge variant="outline" className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300">
                <TrendingUp />0%
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">0%</span>{" "}
              <span className="text-muted-foreground">of all findings</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Est. Recovery / Month</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">$0</span>
              <Badge variant="outline" className="border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300">
                <TrendingUp />0%
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">$0</span>{" "}
              <span className="text-muted-foreground">last month</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Pending Review</CardDescription>
            <CardAction><ArrowUpRight className="size-4" /></CardAction>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-3xl leading-none tracking-tight">0</span>
              <Badge variant="outline" className="border-destructive/20 bg-destructive/10 text-destructive">
                <TrendingDown />0%
              </Badge>
            </div>
            <p className="text-sm">
              <span className="font-medium text-foreground">0%</span>{" "}
              <span className="text-muted-foreground">of findings</span>
            </p>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
