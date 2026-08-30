"use client";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const DAY_MS = 24 * 60 * 60 * 1000;
const weekStart = Date.UTC(2026, 7, 24); // Aug 24

const rawData = [
  { date: "2026-08-24T04:00:00Z", cost: 41000, recovered: 24000 },
  { date: "2026-08-24T12:00:00Z", cost: 43000 },
  { date: "2026-08-24T20:00:00Z", cost: 39000 },
  { date: "2026-08-25T04:00:00Z", cost: 44000, recovered: 27000 },
  { date: "2026-08-25T12:00:00Z", cost: 46000 },
  { date: "2026-08-25T20:00:00Z", cost: 42000 },
  { date: "2026-08-26T04:00:00Z", cost: 40000, recovered: 21000 },
  { date: "2026-08-26T12:00:00Z", cost: 38000 },
  { date: "2026-08-26T20:00:00Z", cost: 41000 },
  { date: "2026-08-27T04:00:00Z", cost: 43000, recovered: 26000 },
  { date: "2026-08-27T12:00:00Z", cost: 45000 },
  { date: "2026-08-27T20:00:00Z", cost: 44000 },
  { date: "2026-08-28T04:00:00Z", cost: 47000, recovered: 29000 },
  { date: "2026-08-28T12:00:00Z", cost: 49000 },
  { date: "2026-08-28T20:00:00Z", cost: 46000 },
  { date: "2026-08-29T04:00:00Z", cost: 44000, recovered: 28000 },
  { date: "2026-08-29T12:00:00Z", cost: 43000 },
  { date: "2026-08-29T20:00:00Z", cost: 42000 },
  { date: "2026-08-30T04:00:00Z", cost: 41000, recovered: 22000 },
];

const chartData = rawData.map((item) => ({ ...item, timestamp: Date.parse(item.date) }));

const weekdayTicks = Array.from({ length: 7 }, (_, i) => weekStart + (i + 0.5) * DAY_MS);
const weekdayFormatter = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "long" });
const formatWeekday = (value: number) => weekdayFormatter.format(new Date(value));
const chartDomain = [weekStart, weekStart + 7 * DAY_MS];

const chartConfig = {
  cost: { color: "var(--chart-4)", label: "GPU Cost" },
  recovered: { color: "var(--chart-2)", label: "Recovered" },
} satisfies ChartConfig;

export function RecoveryCurveCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Recovery Curve</CardTitle>
        <CardAction>
          <Select defaultValue="weekly">
            <SelectTrigger className="w-28" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="weekly">Weekly</SelectItem>
                <SelectItem value="monthly">Monthly</SelectItem>
                <SelectItem value="quarterly">Quarterly</SelectItem>
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
            <Line connectNulls dataKey="recovered" dot={false} stroke="var(--color-recovered)" strokeDasharray="5 5" strokeLinecap="round" strokeWidth={1} type="linear" />
            <Line dataKey="cost" dot={false} stroke="var(--color-cost)" strokeLinecap="round" strokeWidth={3} type="linear" />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
