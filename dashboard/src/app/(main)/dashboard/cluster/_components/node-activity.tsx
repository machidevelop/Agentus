"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const gpuHoursByHour = [
  210, 198, 185, 192, 205, 230, 268, 310, 348, 362, 355, 340,
  338, 345, 372, 380, 365, 350, 332, 315, 290, 268, 245, 222,
] as const;

const chartConfig = {
  gpuHours: {
    label: "Active GPU-hours",
    color: "var(--chart-2)",
  },
} satisfies ChartConfig;

const chartData = gpuHoursByHour.map((gpuHours, index) => ({
  hour: index,
  gpuHours,
  label: `${String(index).padStart(2, "0")}:00`,
}));

const totalGpuHours = chartData.reduce((sum, d) => sum + d.gpuHours, 0);
const peakHours = 284;
const peakProgress = Math.round((peakHours / 400) * 100);

export function NodeActivity() {
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-12">
        <CardHeader>
          <CardTitle>Node Activity (24h)</CardTitle>
          <CardAction>
            <Select defaultValue="last-24h">
              <SelectTrigger size="sm" className="min-w-40">
                <SelectValue placeholder="Select range" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="last-24h">Last 24h</SelectItem>
                  <SelectItem value="last-7d">Last 7d</SelectItem>
                  <SelectItem value="last-30d">Last 30d</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <ChartContainer config={chartConfig} className="h-72 w-full lg:col-span-8">
              <BarChart data={chartData} margin={{ left: 0, right: 0, top: 0, bottom: 0 }} barSize={28}>
                <defs>
                  <pattern
                    id="cluster-gpu-pattern"
                    width="4"
                    height="4"
                    patternUnits="userSpaceOnUse"
                    patternTransform="rotate(45)"
                  >
                    <rect width="6" height="6" fill="var(--color-gpuHours)" fillOpacity="0.15" />
                    <line
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="6"
                      stroke="var(--color-gpuHours)"
                      strokeWidth="1.25"
                      strokeOpacity="0.40"
                    />
                  </pattern>
                </defs>
                <CartesianGrid vertical={false} strokeDasharray="0" />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  tickMargin={10}
                  axisLine={false}
                  interval={3}
                />
                <YAxis hide />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      hideIndicator
                      labelFormatter={(value) => `Hour: ${value}`}
                    />
                  }
                />
                <Bar
                  dataKey="gpuHours"
                  fill="url(#cluster-gpu-pattern)"
                  radius={[8, 8, 0, 0]}
                  stroke="var(--color-gpuHours)"
                  strokeOpacity={0.5}
                  strokeWidth={0.5}
                />
              </BarChart>
            </ChartContainer>

            <div className="flex flex-col gap-5 rounded-lg p-4 lg:col-span-4">
              <div className="flex flex-col gap-1">
                <div className="font-medium text-4xl tabular-nums leading-none">
                  400 <span className="font-normal text-lg text-muted-foreground">GPUs</span>
                </div>
                <p className="text-muted-foreground text-sm">Total GPUs monitored across all nodes in the cluster.</p>
              </div>

              <div className="flex flex-col gap-3 rounded-lg border border-border/60 p-3">
                <div className="text-[11px] text-muted-foreground uppercase tracking-widest">
                  Peak Utilization Window
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="font-medium text-2xl tabular-nums leading-none">
                    14:00–16:00 <span className="font-normal text-muted-foreground text-sm">UTC</span>
                  </div>
                  <p className="text-muted-foreground text-sm">
                    {peakProgress}% of GPUs active during peak window.
                  </p>
                </div>

                <div className="flex flex-col gap-2 pt-0.5">
                  <Progress
                    value={peakProgress}
                    className="h-2.5 bg-chart-2/12 *:data-[slot='progress-indicator']:bg-chart-2"
                  />
                  <div className="flex items-center justify-between text-xs">
                    <div className="font-medium tabular-nums">{peakHours} active</div>
                    <div className="text-muted-foreground tabular-nums">400 total</div>
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
