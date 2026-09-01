"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const findingsChartValues = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] as const;

const findingsChartConfig = {
  findings: {
    label: "Findings",
    color: "var(--chart-1)",
  },
} satisfies ChartConfig;

const axisMonthFormatter = new Intl.DateTimeFormat("en-US", { month: "short" });
const tooltipMonthFormatter = new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit" });

function getRollingMonthData(values: readonly number[]) {
  return values.map((findings, index) => {
    const date = new Date();
    date.setMonth(date.getMonth() - (values.length - 1 - index));
    return { date: date.toISOString(), findings };
  });
}

export function WasteByType() {
  const chartData = getRollingMonthData(findingsChartValues);
  const totalFindings = chartData.reduce((sum, item) => sum + item.findings, 0);
  const queueFindings = 0;
  const queueTarget = 0;
  const queueProgress = Math.round((queueFindings / queueTarget) * 100);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-12">
        <CardHeader>
          <CardTitle>Findings by Type (Monthly)</CardTitle>
          <CardAction>
            <Select defaultValue="this-year">
              <SelectTrigger size="sm" className="min-w-40">
                <SelectValue placeholder="Select range" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="this-year">This Year</SelectItem>
                  <SelectItem value="last-year">Last Year</SelectItem>
                  <SelectItem value="all-time">All time</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <ChartContainer config={findingsChartConfig} className="h-72 w-full lg:col-span-8">
              <BarChart data={chartData} margin={{ left: 0, right: 0, top: 0, bottom: 0 }} barSize={38}>
                <defs>
                  <pattern
                    id="findings-pattern"
                    width="4"
                    height="4"
                    patternUnits="userSpaceOnUse"
                    patternTransform="rotate(45)"
                  >
                    <rect width="6" height="6" fill="var(--color-findings)" fillOpacity="0.15" />
                    <line
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="6"
                      stroke="var(--color-findings)"
                      strokeWidth="1.25"
                      strokeOpacity="0.40"
                    />
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
                  dataKey="findings"
                  fill="url(#findings-pattern)"
                  radius={[8, 8, 0, 0]}
                  stroke="var(--color-findings)"
                  strokeOpacity={0.5}
                  strokeWidth={0.5}
                />
              </BarChart>
            </ChartContainer>

            <div className="flex flex-col gap-5 rounded-lg p-4 lg:col-span-4">
              <div className="flex flex-col gap-1">
                <div className="font-medium text-4xl tabular-nums leading-none">
                  {totalFindings.toLocaleString()}{" "}
                  <span className="font-normal text-lg text-muted-foreground">total</span>
                </div>
                <p className="text-muted-foreground text-sm">Total findings detected over the last 12 months.</p>
              </div>

              <div className="flex flex-col gap-3 rounded-lg border border-border/60 p-3">
                <div className="text-[11px] text-muted-foreground uppercase tracking-widest">
                  Queue Findings This Month
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="font-medium text-2xl tabular-nums leading-none">
                    {queueFindings}{" "}
                    <span className="font-normal text-muted-foreground text-sm">found</span>
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {queueProgress}% of {queueTarget} target threshold.
                  </p>
                </div>

                <div className="flex flex-col gap-2 pt-0.5">
                  <Progress
                    value={queueProgress}
                    className="h-2.5 bg-chart-1/12 *:data-[slot='progress-indicator']:bg-chart-1"
                  />
                  <div className="flex items-center justify-between text-xs">
                    <div className="font-medium tabular-nums">{queueFindings} found</div>
                    <div className="text-muted-foreground tabular-nums">{queueTarget} target</div>
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
