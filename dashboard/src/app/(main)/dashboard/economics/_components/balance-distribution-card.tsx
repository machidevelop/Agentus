"use client";

import * as React from "react";

import { Label, Pie, PieChart } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type ValueKey = "frag" | "idle" | "over" | "queue";

const valueData: {
  account: string;
  amount: number;
  key: ValueKey;
  percentage: number;
}[] = [
  { account: "Idle Allocation", amount: 406_180, key: "idle", percentage: 75.9 },
  { account: "Queue Inefficiency", amount: 129_005, key: "queue", percentage: 24.1 },
  { account: "Over-Allocation", amount: 67_200, key: "over", percentage: 12.6 },
  { account: "Fragmentation", amount: 14_800, key: "frag", percentage: 2.8 },
];

const chartConfig = {
  amount: { label: "Value" },
  frag: { color: "var(--chart-4)", label: "Fragmentation" },
  idle: { color: "var(--chart-1)", label: "Idle Allocation" },
  over: { color: "var(--chart-3)", label: "Over-Allocation" },
  queue: { color: "var(--chart-2)", label: "Queue Inefficiency" },
} satisfies ChartConfig;

const gpuTypes = {
  "A100-80GB": { label: "A100-80GB @ $2.21/hr" },
  "H100-80GB": { label: "H100-80GB @ $3.28/hr" },
  "V100-32GB": { label: "V100-32GB @ $1.47/hr" },
} as const;

type GpuType = keyof typeof gpuTypes;

const getColor = (key: ValueKey) => {
  const config = chartConfig[key];
  return "color" in config ? config.color : undefined;
};

const chartData = valueData.map((item) => ({ ...item, fill: getColor(item.key) }));
const totalValue = 535_185;

function formatCurrency(val: number) {
  return `$${val.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function BalanceDistributionCard() {
  const [gpuType, setGpuType] = React.useState<GpuType>("A100-80GB");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">GPU Value Allocation</CardTitle>
        <CardAction>
          <Select onValueChange={(v) => setGpuType(v as GpuType)} value={gpuType}>
            <SelectTrigger className="w-44" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {Object.entries(gpuTypes).map(([value, item]) => (
                  <SelectItem key={value} value={value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>

      <CardContent className="grid items-center gap-4 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)]">
        <ChartContainer config={chartConfig} className="mx-auto aspect-square h-50">
          <PieChart>
            <ChartTooltip
              cursor={false}
              content={<ChartTooltipContent hideLabel className="w-52" nameKey="account" />}
            />
            <Pie
              cornerRadius={6}
              data={chartData}
              dataKey="amount"
              innerRadius={65}
              nameKey="account"
              outerRadius={90}
              paddingAngle={2}
              strokeWidth={5}
            >
              <Label
                content={({ viewBox }) => {
                  if (!(viewBox && "cx" in viewBox && "cy" in viewBox)) return null;
                  return (
                    <text dominantBaseline="middle" textAnchor="middle" x={viewBox.cx} y={viewBox.cy}>
                      <tspan className="fill-muted-foreground text-xs" x={viewBox.cx} y={(viewBox.cy ?? 0) - 8}>
                        Total
                      </tspan>
                      <tspan
                        className="fill-foreground font-medium text-lg tabular-nums"
                        x={viewBox.cx}
                        y={(viewBox.cy ?? 0) + 14}
                      >
                        {formatCurrency(totalValue)}
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
                  <p className="truncate text-muted-foreground text-xs">{item.account}</p>
                </div>
                <p className="font-medium tabular-nums">{formatCurrency(item.amount)}</p>
              </div>
              <div className="font-medium tabular-nums">{item.percentage}%</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
