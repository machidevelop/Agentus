"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const DAY_MS = 24 * 60 * 60 * 1000;
const weekStart = Date.UTC(2026, 0, 5);

const rawData = [
  { date: "2026-01-05T02:00:00Z", recovered: 320, baseline: 580 },
  { date: "2026-01-05T08:00:00Z", recovered: 410, baseline: 610 },
  { date: "2026-01-05T14:00:00Z", recovered: 390, baseline: 595 },
  { date: "2026-01-05T20:00:00Z", recovered: 450, baseline: 620 },
  { date: "2026-01-06T02:00:00Z", recovered: 480, baseline: 640 },
  { date: "2026-01-06T08:00:00Z", recovered: 520, baseline: 660 },
  { date: "2026-01-06T14:00:00Z", recovered: 490, baseline: 650 },
  { date: "2026-01-06T20:00:00Z", recovered: 560, baseline: 680 },
  { date: "2026-01-07T02:00:00Z", recovered: 430, baseline: 630 },
  { date: "2026-01-07T08:00:00Z", recovered: 510, baseline: 655 },
  { date: "2026-01-07T14:00:00Z", recovered: 570, baseline: 690 },
  { date: "2026-01-07T20:00:00Z", recovered: 600, baseline: 710 },
  { date: "2026-01-08T02:00:00Z", recovered: 540, baseline: 670 },
  { date: "2026-01-08T08:00:00Z", recovered: 580, baseline: 695 },
  { date: "2026-01-08T14:00:00Z", recovered: 620, baseline: 720 },
  { date: "2026-01-08T20:00:00Z", recovered: 650, baseline: 740 },
  { date: "2026-01-09T02:00:00Z", recovered: 590, baseline: 700 },
  { date: "2026-01-09T08:00:00Z", recovered: 630, baseline: 725 },
  { date: "2026-01-09T14:00:00Z", recovered: 680, baseline: 760 },
  { date: "2026-01-09T20:00:00Z", recovered: 710, baseline: 780 },
  { date: "2026-01-10T02:00:00Z", recovered: 660, baseline: 745 },
  { date: "2026-01-10T08:00:00Z", recovered: 700, baseline: 770 },
  { date: "2026-01-10T14:00:00Z", recovered: 740, baseline: 795 },
  { date: "2026-01-10T20:00:00Z", recovered: 780, baseline: 820 },
  { date: "2026-01-11T02:00:00Z", recovered: 720, baseline: 785 },
  { date: "2026-01-11T08:00:00Z", recovered: 760, baseline: 810 },
  { date: "2026-01-11T14:00:00Z", recovered: 800, baseline: 840 },
  { date: "2026-01-11T20:00:00Z", recovered: 830, baseline: 860 },
  { date: "2026-01-12T02:00:00Z", recovered: 790, baseline: 825 },
  { date: "2026-01-12T08:00:00Z", recovered: 850, baseline: 870 },
];

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
