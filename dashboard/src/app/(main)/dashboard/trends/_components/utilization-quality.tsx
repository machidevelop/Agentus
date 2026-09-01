"use client";
import { Ellipsis } from "lucide-react";
import { CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const series: { date: string; actual: number; target?: number }[] = [];

const chartConfig = {
  actual: { color: "var(--chart-3)", label: "Actual Utilization" },
  target: { color: "var(--muted-foreground)", label: "Target (70%)" },
} satisfies ChartConfig;

const chartData = series.map((item, index) => ({ ...item, dayIndex: 1 + (index * 27) / (series.length - 1) }));
const weeklyTicks = [4, 11, 18, 25];
function formatWeek(value: number) {
  const wi = weeklyTicks.indexOf(value);
  return wi >= 0 ? `Week ${wi + 1}` : "";
}

export function UtilizationQuality() {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="font-normal">Utilization Quality</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-68 w-full">
          <ComposedChart data={chartData} margin={{ bottom: 0, left: 0, right: 0, top: 0 }}>
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
              domain={[40, 80]}
              tickFormatter={(v) => `${v}%`}
              tickLine={false}
              tickMargin={10}
              width={38}
            />
            <ChartTooltip cursor={false} content={<ChartTooltipContent className="w-44" labelFormatter={() => "Utilization"} />} />
            <Line dataKey="target" dot={false} stroke="var(--color-target)" strokeOpacity={0.65} strokeDasharray="4 4" strokeWidth={1.75} type="linear" connectNulls />
            <Line dataKey="actual" dot={false} activeDot={{ r: 4 }} stroke="var(--color-actual)" strokeWidth={2.5} type="linear" />
          </ComposedChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
