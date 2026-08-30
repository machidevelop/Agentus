"use client";

import { Ellipsis } from "lucide-react";
import { CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const seed = (n: number) => {
  let x = Math.sin(n + 1) * 10000;
  return x - Math.floor(x);
};

const recoverySeries = Array.from({ length: 84 }, (_, i) => {
  const t = i / 83;
  const recovered = 8000 + 6000 * t + (seed(i * 3) - 0.5) * 3000;
  const wasted = 22000 - 4000 * t + (seed(i * 7 + 1) - 0.5) * 2500;
  return {
    date: `2026-04-${String(1 + Math.floor(i / 3)).padStart(2, "0")}`,
    dayIndex: 1 + (i * 27) / 83,
    recoveredGpuHours: Math.round(recovered),
    wastedGpuHours: Math.round(wasted),
  };
});

const chartConfig = {
  recoveredGpuHours: { color: "var(--chart-3)", label: "Recovered GPU-hours" },
  wastedGpuHours: { color: "var(--muted-foreground)", label: "Wasted GPU-hours" },
} satisfies ChartConfig;

const weeklyTicks = [4, 11, 18, 25];

function formatWeek(value: number) {
  const weekIndex = weeklyTicks.indexOf(value);
  return weekIndex >= 0 ? `Week ${weekIndex + 1}` : "";
}

function formatK(value: number) {
  return `${Math.round(value / 1000)}k`;
}

export function RecoveryTrend() {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="font-normal">Recovery vs Waste Trend</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-68 w-full">
          <ComposedChart data={recoverySeries} margin={{ bottom: 0, left: 0, right: 0, top: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="dayIndex"
              axisLine={false}
              domain={[1, 28]}
              interval={0}
              tickFormatter={formatWeek}
              tickLine={false}
              tickMargin={14}
              ticks={weeklyTicks}
              type="number"
            />
            <YAxis
              axisLine={false}
              domain={[0, 26000]}
              tickFormatter={formatK}
              tickLine={false}
              tickMargin={10}
              width={34}
            />
            <ChartTooltip
              cursor={false}
              content={<ChartTooltipContent className="w-48" labelFormatter={() => "GPU-hours"} />}
            />
            <Line
              dataKey="wastedGpuHours"
              dot={false}
              stroke="var(--color-wastedGpuHours)"
              strokeOpacity={0.65}
              strokeDasharray="4 4"
              strokeWidth={1.75}
              type="linear"
            />
            <Line
              dataKey="recoveredGpuHours"
              dot={false}
              activeDot={{ r: 4 }}
              stroke="var(--color-recoveredGpuHours)"
              strokeWidth={2.5}
              type="linear"
            />
          </ComposedChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
