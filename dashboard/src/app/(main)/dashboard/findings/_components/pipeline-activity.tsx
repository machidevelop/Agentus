"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const detectedValues = [312, 344, 298, 421, 387, 456, 412, 398, 521, 478, 445, 492] as const;

const chartConfig = {
  detected: { label: "Detected", color: "var(--chart-1)" },
} satisfies ChartConfig;

const axisMonthFormatter = new Intl.DateTimeFormat("en-US", { month: "short" });
const tooltipMonthFormatter = new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit" });

function getRollingMonthData(values: readonly number[]) {
  return values.map((detected, index) => {
    const date = new Date("2026-08-30");
    date.setMonth(date.getMonth() - (values.length - 1 - index));
    return { date: date.toISOString(), detected };
  });
}

export function PipelineActivity() {
  const chartData = getRollingMonthData(detectedValues);
  const totalDetected = chartData.reduce((sum, item) => sum + item.detected, 0);
  const resolved = 3841;
  const resolveRate = Math.round((resolved / totalDetected) * 100);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-12">
        <CardHeader>
          <CardTitle>Finding Detection Flow</CardTitle>
          <CardAction>
            <Select defaultValue="last-12-months">
              <SelectTrigger size="sm" className="min-w-40">
                <SelectValue placeholder="Select range" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="last-30-days">Last 30 days</SelectItem>
                  <SelectItem value="last-quarter">Last quarter</SelectItem>
                  <SelectItem value="last-12-months">Last 12 months</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <ChartContainer config={chartConfig} className="h-72 w-full lg:col-span-8">
              <BarChart data={chartData} margin={{ left: 0, right: 0, top: 0, bottom: 0 }} barSize={38}>
                <defs>
                  <pattern id="findings-detected-pattern" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                    <rect width="6" height="6" fill="var(--color-detected)" fillOpacity="0.15" />
                    <line x1="0" y1="0" x2="0" y2="6" stroke="var(--color-detected)" strokeWidth="1.25" strokeOpacity="0.40" />
                  </pattern>
                </defs>
                <CartesianGrid vertical={false} strokeDasharray="0" />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  tickMargin={10}
                  axisLine={false}
                  tickFormatter={(value) => axisMonthFormatter.format(new Date(String(value)))}
                />
                <YAxis hide />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      hideIndicator
                      labelFormatter={(value) => tooltipMonthFormatter.format(new Date(String(value)))}
                    />
                  }
                />
                <Bar
                  dataKey="detected"
                  fill="url(#findings-detected-pattern)"
                  radius={[8, 8, 0, 0]}
                  stroke="var(--color-detected)"
                  strokeOpacity={0.5}
                  strokeWidth={0.5}
                />
              </BarChart>
            </ChartContainer>
            <div className="flex flex-col gap-5 rounded-lg p-4 lg:col-span-4">
              <div className="flex flex-col gap-1">
                <div className="font-medium text-4xl tabular-nums leading-none">
                  {totalDetected.toLocaleString()} <span className="font-normal text-lg text-muted-foreground">findings</span>
                </div>
                <p className="text-muted-foreground text-sm">Total GPU waste findings detected over the last 12 months.</p>
              </div>
              <div className="flex flex-col gap-3 rounded-lg border border-border/60 p-3">
                <div className="text-[11px] text-muted-foreground uppercase tracking-widest">Findings Resolved</div>
                <div className="flex flex-col gap-1.5">
                  <div className="font-medium text-2xl tabular-nums leading-none">
                    {resolved.toLocaleString()} <span className="font-normal text-muted-foreground text-sm">resolved</span>
                  </div>
                  <p className="text-muted-foreground text-sm">{resolveRate}% of detected findings were actioned.</p>
                </div>
                <div className="flex flex-col gap-2 pt-0.5">
                  <Progress value={resolveRate} className="h-2.5 bg-chart-1/12 *:data-[slot='progress-indicator']:bg-chart-1" />
                  <div className="flex items-center justify-between text-xs">
                    <div className="font-medium tabular-nums">{resolved.toLocaleString()} resolved</div>
                    <div className="text-muted-foreground tabular-nums">{totalDetected.toLocaleString()} detected</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
