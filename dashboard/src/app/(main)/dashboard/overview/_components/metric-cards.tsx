"use client";
import { Activity, DollarSign, Layers, TrendingDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const metrics = [
  {
    label: "Monthly Recovery",
    value: "$0",
    change: "0%",
    positive: true,
    icon: DollarSign,
    iconBg: "bg-emerald-500/10",
    iconColor: "text-emerald-600 dark:text-emerald-400",
  },
  {
    label: "Active Findings",
    value: "0",
    change: "0%",
    positive: true,
    icon: Activity,
    iconBg: "bg-blue-500/10",
    iconColor: "text-blue-600 dark:text-blue-400",
  },
  {
    label: "GPU-Hours Wasted",
    value: "0",
    change: "0%",
    positive: false,
    icon: TrendingDown,
    iconBg: "bg-red-500/10",
    iconColor: "text-red-600 dark:text-red-400",
  },
  {
    label: "Avg Queue Wait",
    value: "0 min",
    change: "0%",
    positive: false,
    icon: Layers,
    iconBg: "bg-amber-500/10",
    iconColor: "text-amber-600 dark:text-amber-400",
  },
];

export function MetricCards() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map((m) => (
        <Card key={m.label}>
          <CardContent className="flex items-start justify-between gap-4 p-5">
            <div className="flex flex-col gap-2">
              <span className="text-muted-foreground text-sm">{m.label}</span>
              <span className="font-semibold text-2xl tracking-tight">{m.value}</span>
              <Badge
                variant="outline"
                className={cn(
                  "w-fit gap-1 rounded-full text-xs",
                  m.positive
                    ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                    : "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300"
                )}
              >
                {m.change} vs last month
              </Badge>
            </div>
            <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg", m.iconBg)}>
              <m.icon className={cn("size-5", m.iconColor)} />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
