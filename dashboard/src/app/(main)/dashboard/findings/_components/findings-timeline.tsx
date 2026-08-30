import { BarChart2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const monthlyValue = 535_185;
const monthlyTarget = 600_000;
const valueProgressPercentage = Math.round((monthlyValue / monthlyTarget) * 100);
const valueGoalBarCount = 42;
const activeValueBars = Math.round((monthlyValue / monthlyTarget) * valueGoalBarCount);

const valueGoalBars = Array.from({ length: valueGoalBarCount }, (_, index) => ({
  id: `value-goal-${index + 1}`,
  active: index < activeValueBars,
}));

const wasteSegments = [
  { label: "Idle Allocation", count: 2088, pct: 81.6, color: "bg-amber-500" },
  { label: "Queue Inefficiency", count: 269, pct: 10.5, color: "bg-blue-500" },
  { label: "Over-Allocation", count: 168, pct: 6.6, color: "bg-purple-500" },
  { label: "Fragmentation", count: 33, pct: 1.3, color: "bg-green-500" },
];

export function FindingsTimeline() {
  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-8">
        <CardHeader>
          <CardTitle>Waste Distribution (43.3h window)</CardTitle>
          <CardAction>
            <Button variant="outline" size="sm">
              <BarChart2 data-icon="inline-start" />
              View Details
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between text-muted-foreground text-xs tabular-nums">
              {wasteSegments.map((seg) => (
                <div key={seg.label} className="flex flex-col items-center gap-1">
                  <span>{seg.pct}%</span>
                  <span className="h-2 w-px bg-border" />
                </div>
              ))}
            </div>

            <div className="relative h-14">
              <div className="absolute inset-x-3 top-1/2 h-px -translate-y-1/2 bg-border/80" />
              {(() => {
                let offset = 0;
                return wasteSegments.map((seg) => {
                  const width = seg.pct;
                  const left = offset;
                  offset += width;
                  return (
                    <div
                      key={seg.label}
                      className={cn(
                        "absolute top-2 bottom-2 flex items-center rounded-lg px-2 text-white shadow-sm",
                        seg.color,
                      )}
                      style={{ left: `${left}%`, width: `${width - 1}%` }}
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium text-xs leading-none">{seg.label}</div>
                        <div className="truncate text-[10px] opacity-80">{seg.count.toLocaleString()} findings</div>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>

            <div className="grid grid-cols-2 gap-3 pt-2 sm:grid-cols-4">
              {wasteSegments.map((seg) => (
                <div key={seg.label} className="flex items-center gap-2">
                  <div className={cn("size-2 rounded-full shrink-0", seg.color)} />
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium">{seg.label}</div>
                    <div className="text-xs text-muted-foreground tabular-nums">{seg.count.toLocaleString()}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="xl:col-span-4">
        <CardHeader>
          <CardTitle>Monthly Value Goal</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-1">
          <div className="flex items-end justify-between gap-3">
            <div className="font-medium text-2xl tabular-nums leading-none">
              ${(monthlyValue / 1000).toFixed(0)}k{" "}
              <span className="font-normal text-base text-muted-foreground">recovered</span>
            </div>
            <div className="text-muted-foreground text-sm tabular-nums">${(monthlyTarget / 1000).toFixed(0)}k target</div>
          </div>
          <div className="flex h-10 w-full items-end gap-0.5">
            {valueGoalBars.map((bar) => (
              <div key={bar.id} className="flex flex-1 justify-center">
                <div
                  className={cn(
                    "h-10 w-1.5 rounded-full",
                    bar.active ? "bg-muted-foreground/75" : "bg-muted-foreground/25",
                  )}
                />
              </div>
            ))}
          </div>
          <p className="text-muted-foreground text-sm">
            {valueProgressPercentage}% of this month&apos;s recovery target reached.
          </p>
        </CardContent>
      </Card>
    </section>
  );
}
