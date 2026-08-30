"use client";
import * as React from "react";
import { Label, Pie, PieChart } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type WasteKey = "idle_allocation" | "queue_inefficiency" | "over_allocation" | "fragmentation";

const wasteData: { category: string; amount: number; key: WasteKey; percentage: number }[] = [
  { category: "Idle Allocation", amount: 218000, key: "idle_allocation", percentage: 40.7 },
  { category: "Queue Inefficiency", amount: 156000, key: "queue_inefficiency", percentage: 29.1 },
  { category: "Over-Allocation", amount: 97000, key: "over_allocation", percentage: 18.1 },
  { category: "Fragmentation", amount: 64185, key: "fragmentation", percentage: 12.1 },
];

const chartConfig = {
  amount: { label: "Waste" },
  idle_allocation: { color: "var(--chart-1)", label: "Idle Allocation" },
  queue_inefficiency: { color: "var(--chart-2)", label: "Queue Inefficiency" },
  over_allocation: { color: "var(--chart-3)", label: "Over-Allocation" },
  fragmentation: { color: "var(--chart-4)", label: "Fragmentation" },
} satisfies ChartConfig;

const currencies = {
  USD: { label: "USD Value" },
  EUR: { label: "EUR Value" },
  GBP: { label: "GBP Value" },
} as const;
type Currency = keyof typeof currencies;

const getColor = (key: WasteKey) => {
  const cfg = chartConfig[key];
  return "color" in cfg ? cfg.color : undefined;
};

const chartData = wasteData.map((item) => ({ ...item, fill: getColor(item.key) }));
const totalWaste = wasteData.reduce((t, i) => t + i.amount, 0);

export function WasteDistributionCard() {
  const [currency, setCurrency] = React.useState<Currency>("USD");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Waste Distribution</CardTitle>
        <CardAction>
          <Select onValueChange={(v) => setCurrency(v as Currency)} value={currency}>
            <SelectTrigger className="w-32" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {Object.entries(currencies).map(([v, item]) => (
                  <SelectItem key={v} value={v}>{item.label}</SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent className="grid items-center gap-4 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)]">
        <ChartContainer config={chartConfig} className="mx-auto aspect-square h-50">
          <PieChart>
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel className="w-52" nameKey="category" />} />
            <Pie cornerRadius={6} data={chartData} dataKey="amount" innerRadius={65} nameKey="category" outerRadius={90} paddingAngle={2} strokeWidth={5}>
              <Label
                content={({ viewBox }) => {
                  if (!(viewBox && "cx" in viewBox && "cy" in viewBox)) return null;
                  return (
                    <text dominantBaseline="middle" textAnchor="middle" x={viewBox.cx} y={viewBox.cy}>
                      <tspan className="fill-muted-foreground text-xs" x={viewBox.cx} y={(viewBox.cy ?? 0) - 8}>Total</tspan>
                      <tspan className="fill-foreground font-medium text-lg tabular-nums" x={viewBox.cx} y={(viewBox.cy ?? 0) + 14}>
                        ${Math.round(totalWaste / 1000)}k
                      </tspan>
                    </text>
                  );
                }}
              />
            </Pie>
          </PieChart>
        </ChartContainer>
        <div className="flex min-w-0 flex-col gap-3">
          {chartData.map((item) => (
            <div className="grid grid-cols-[1fr_auto] items-end gap-3" key={item.key}>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-1">
                  <span aria-hidden="true" className="h-2 w-1 rounded-full" style={{ backgroundColor: item.fill }} />
                  <p className="truncate text-muted-foreground text-xs">{item.category}</p>
                </div>
                <p className="font-medium tabular-nums">${item.amount.toLocaleString()}</p>
              </div>
              <div className="font-medium tabular-nums">{item.percentage}%</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
