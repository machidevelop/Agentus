"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const DAY_MS = 24 * 60 * 60 * 1000;
const weekStart = Date.UTC(2026, 0, 5);

const rawData = Array.from({ length: 7 }, (_, i) => ({
  date: `2026-01-${String(5 + i).padStart(2, "0")}T12:00:00Z`,
  recovered: 0,
  baseline: 0,
}));

const chartData = rawData.map((item) => ({
  ...item,
  timestamp: Date.parse(item.date),
}));

const weekdayTicks = Array.from({ length: 7 }, (_, i) => weekStart + (i + 0.5) * DAY_MS);
const weekdayFormatter = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short" });
const formatWeekday = (value: number) => weekdayFormatter.format(new Date(value));
const chartDomain = [weekStart, weekStart + 7 * DAY_MS];

const chartConfig = {
  baseline: { color: "var(--chart-4)", label: "Waste baseline (GPU-hrs)" },
  recovered: { color: "var(--chart-2)", label: "GPU-hours recovered" },
} satisfies ChartConfig;

export function RecoveryTimeline() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Recovery Timeline</CardTitle>
        <CardAction>
          <Select defaultValue="weekly">
            <SelectTrigger className="w-28" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="weekly">Weekly</SelectItem>
                <SelectItem value="monthly">Monthly</SelectItem>
                <SelectItem value="yearly">Yearly</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>

      <CardContent>
        <ChartContainer config={chartConfig} className="h-50 w-full">
          <LineChart accessibilityLayer data={chartData} margin={{ bottom: 0, left: 0, right: 0, top: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              axisLine={false}
              dataKey="timestamp"
              domain={chartDomain}
              scale="time"
              tickFormatter={formatWeekday}
              tickLine={false}
              tickMargin={10}
              ticks={weekdayTicks}
              tick={{ fontSize: 12 }}
              type="number"
            />
            <YAxis hide axisLine={false} tickLine={false} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
            <Line
              connectNulls
              dataKey="baseline"
              dot={false}
              stroke="var(--color-baseline)"
              strokeDasharray="5 5"
              strokeLinecap="round"
              strokeWidth={1.5}
              type="linear"
            />
            <Line
              dataKey="recovered"
              dot={false}
              stroke="var(--color-recovered)"
              strokeLinecap="round"
              strokeWidth={3}
              type="linear"
            />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
