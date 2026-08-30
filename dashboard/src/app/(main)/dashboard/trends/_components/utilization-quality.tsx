"use client";
import { Ellipsis } from "lucide-react";
import { CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const series = [
  { date: "2026-08-01T00:00:00Z", actual: 58, target: 70 },
  { date: "2026-08-01T08:00:00Z", actual: 61 },
  { date: "2026-08-01T16:00:00Z", actual: 63 },
  { date: "2026-08-02T00:00:00Z", actual: 60, target: 70 },
  { date: "2026-08-02T08:00:00Z", actual: 62 },
  { date: "2026-08-02T16:00:00Z", actual: 65 },
  { date: "2026-08-03T00:00:00Z", actual: 67, target: 70 },
  { date: "2026-08-03T08:00:00Z", actual: 70 },
  { date: "2026-08-03T16:00:00Z", actual: 68 },
  { date: "2026-08-04T00:00:00Z", actual: 66, target: 70 },
  { date: "2026-08-04T08:00:00Z", actual: 64 },
  { date: "2026-08-04T16:00:00Z", actual: 59 },
  { date: "2026-08-05T00:00:00Z", actual: 57, target: 70 },
  { date: "2026-08-05T08:00:00Z", actual: 55 },
  { date: "2026-08-05T16:00:00Z", actual: 53 },
  { date: "2026-08-06T00:00:00Z", actual: 56, target: 70 },
  { date: "2026-08-06T08:00:00Z", actual: 59 },
  { date: "2026-08-06T16:00:00Z", actual: 62 },
  { date: "2026-08-07T00:00:00Z", actual: 64, target: 70 },
  { date: "2026-08-07T08:00:00Z", actual: 61 },
  { date: "2026-08-07T16:00:00Z", actual: 58 },
  { date: "2026-08-08T00:00:00Z", actual: 60, target: 70 },
  { date: "2026-08-08T08:00:00Z", actual: 63 },
  { date: "2026-08-08T16:00:00Z", actual: 65 },
  { date: "2026-08-09T00:00:00Z", actual: 67, target: 70 },
  { date: "2026-08-09T08:00:00Z", actual: 69 },
  { date: "2026-08-09T16:00:00Z", actual: 71 },
  { date: "2026-08-10T00:00:00Z", actual: 68, target: 70 },
  { date: "2026-08-10T08:00:00Z", actual: 65 },
  { date: "2026-08-10T16:00:00Z", actual: 62 },
  { date: "2026-08-11T00:00:00Z", actual: 59, target: 70 },
  { date: "2026-08-11T08:00:00Z", actual: 57 },
  { date: "2026-08-11T16:00:00Z", actual: 54 },
  { date: "2026-08-12T00:00:00Z", actual: 56, target: 70 },
  { date: "2026-08-12T08:00:00Z", actual: 58 },
  { date: "2026-08-12T16:00:00Z", actual: 60 },
  { date: "2026-08-13T00:00:00Z", actual: 62, target: 70 },
  { date: "2026-08-13T08:00:00Z", actual: 64 },
  { date: "2026-08-13T16:00:00Z", actual: 61 },
  { date: "2026-08-14T00:00:00Z", actual: 59, target: 70 },
  { date: "2026-08-14T08:00:00Z", actual: 61 },
  { date: "2026-08-14T16:00:00Z", actual: 63 },
];

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
