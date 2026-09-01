"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";

const data = [
  { type: "Idle Allocation", count: 0 },
  { type: "Queue Inefficiency", count: 0 },
  { type: "Over-Allocation", count: 0 },
  { type: "Fragmentation", count: 0 },
];

const chartConfig = {
  count: {
    label: "Findings",
    color: "var(--chart-1)",
  },
} satisfies ChartConfig;

export function FindingsChart() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Findings by Type</CardTitle>
        <CardDescription>Distribution of waste findings across all monitored jobs</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
          <BarChart data={data} layout="vertical" margin={{ left: 16, right: 16 }}>
            <CartesianGrid horizontal={false} />
            <YAxis
              dataKey="type"
              type="category"
              tickLine={false}
              axisLine={false}
              width={130}
            />
            <XAxis type="number" tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="count" fill="var(--color-count)" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
