"use client";
import * as React from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import type { ChartConfig } from "@/components/ui/chart";

const chartConfig = {
  wasteDetected: { label: "Waste Detected ($)", color: "hsl(var(--chart-1))" },
  recovered: { label: "Recovered ($)", color: "hsl(var(--chart-2))" },
  queued: { label: "In Queue ($)", color: "hsl(var(--chart-3))" },
} satisfies ChartConfig;

function generateData() {
  const data = [];
  const now = new Date("2026-08-30");
  for (let i = 167; i >= 0; i--) {
    const d = new Date(now);
    d.setHours(now.getHours() - i);
    const hour = d.getHours();
    const base = 3000 + Math.sin(i / 12) * 800;
    const waste = Math.round(base + Math.random() * 600);
    const recovered = Math.round(waste * (0.6 + Math.random() * 0.2));
    const queued = Math.round(waste * (0.1 + Math.random() * 0.15));
    data.push({
      time: d.toLocaleTimeString("en-US", { hour: "2-digit", hour12: false }) + (i % 24 === 0 ? ` ${d.getDate()}` : ""),
      wasteDetected: waste,
      recovered,
      queued,
    });
  }
  return data;
}

const allData = generateData();

export function RecoveryOverview() {
  const [period, setPeriod] = React.useState("24h");

  const sliceMap: Record<string, number> = { "24h": 24, "48h": 48, "7d": 168 };
  const data = allData.slice(-sliceMap[period]);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-1">
          <CardTitle>Recovery Overview</CardTitle>
          <CardDescription>Waste detected vs recovered GPU value over time</CardDescription>
        </div>
        <CardAction>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="24h">Last 24h</SelectItem>
              <SelectItem value="48h">Last 48h</SelectItem>
              <SelectItem value="7d">Last 7d</SelectItem>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="h-72 w-full">
          <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="gradWaste" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="hsl(var(--chart-1))" stopOpacity={0.3} />
                <stop offset="95%" stopColor="hsl(var(--chart-1))" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} className="stroke-border/50" />
            <XAxis
              dataKey="time"
              tickLine={false}
              axisLine={false}
              className="text-muted-foreground text-xs"
              interval={Math.floor(data.length / 6)}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              className="text-muted-foreground text-xs"
              tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Area
              type="monotone"
              dataKey="wasteDetected"
              stroke="hsl(var(--chart-1))"
              fill="url(#gradWaste)"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="recovered"
              stroke="hsl(var(--chart-2))"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="queued"
              stroke="hsl(var(--chart-3))"
              strokeWidth={2}
              dot={false}
              strokeDasharray="4 4"
            />
          </ComposedChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
