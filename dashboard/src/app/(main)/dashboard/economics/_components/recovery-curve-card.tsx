"use client";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const DAY_MS = 24 * 60 * 60 * 1000;
const weekStart = (() => { const d = new Date(); d.setDate(d.getDate() - 6); d.setUTCHours(0,0,0,0); return d.getTime(); })();

const rawData = Array.from({ length: 7 }, (_, i) => ({
  date: new Date(weekStart + i * DAY_MS).toISOString(),
  cost: 0,
  recovered: 0,
}));

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
