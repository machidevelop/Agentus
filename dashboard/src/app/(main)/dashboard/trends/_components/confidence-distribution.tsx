"use client";

import { Ellipsis } from "lucide-react";
import { Bar, BarChart, type BarShapeProps, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const confidenceData = [
  { bucket: 1, count: 2 }, { bucket: 2, count: 4 }, { bucket: 3, count: 6 },
  { bucket: 4, count: 8 }, { bucket: 5, count: 10 }, { bucket: 6, count: 14 },
  { bucket: 7, count: 18 }, { bucket: 8, count: 22 }, { bucket: 9, count: 28 },
  { bucket: 10, count: 36 }, { bucket: 11, count: 52 }, { bucket: 12, count: 74 },
  { bucket: 13, count: 98 }, { bucket: 14, count: 130 }, { bucket: 15, count: 180 },
  { bucket: 16, count: 240 }, { bucket: 17, count: 340 }, { bucket: 18, count: 480 },
  { bucket: 19, count: 620 }, { bucket: 20, count: 780 }, { bucket: 21, count: 820 },
  { bucket: 22, count: 740 }, { bucket: 23, count: 580 }, { bucket: 24, count: 420 },
  { bucket: 25, count: 280 }, { bucket: 26, count: 160 }, { bucket: 27, count: 90 },
  { bucket: 28, count: 48 }, { bucket: 29, count: 22 }, { bucket: 30, count: 8 },
];

const chartConfig = {
  count: {
    color: "var(--chart-3)",
    label: "Findings",
  },
} satisfies ChartConfig;

function ConfidenceBarShape(props: BarShapeProps) {
  const { height, payload, width, x, y } = props;
  const barPayload = payload as (typeof confidenceData)[number] | undefined;
  const barHeightValue = Number(height);
  const barWidthValue = Number(width);
  const xValue = Number(x);
  const yValue = Number(y);
  const count = barPayload?.count ?? 0;
  const fill = "var(--color-count)";
  const fillOpacity = count >= 600 ? 0.95 : 0.4;
  const baselineFill = count === 0 ? "var(--destructive)" : fill;
  const baselineOpacity = count === 0 ? 1 : fillOpacity;
  const baselineY = yValue + barHeightValue - 2;
  const barGap = 4;
  const barHeight = Math.max(0, barHeightValue - barGap);

  return (
    <g>
      <rect x={xValue} y={baselineY} width={barWidthValue} height={2} rx={1}
        fill={baselineFill} fillOpacity={baselineOpacity} />
      {count > 0 && barHeight > 0 ? (
        <rect x={xValue} y={yValue} width={barWidthValue} height={barHeight} rx={2}
          fill={fill} fillOpacity={fillOpacity} />
      ) : null}
    </g>
  );
}

export function ConfidenceDistribution() {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="font-normal">Confidence Distribution</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-end justify-between">
          <div className="flex items-baseline gap-1">
            <span className="text-2xl tabular-nums leading-none tracking-tight">97.4%</span>
            <span className="text-muted-foreground text-sm">high confidence</span>
          </div>
        </div>
        <ChartContainer config={chartConfig} className="h-36 w-full">
          <BarChart data={confidenceData} margin={{ bottom: 0, left: 0, right: 0, top: 0 }} barCategoryGap={3}>
            <XAxis dataKey="bucket" hide />
            <YAxis hide domain={[0, 900]} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" fill="var(--color-count)" shape={ConfidenceBarShape} />
          </BarChart>
        </ChartContainer>
        <div className="grid grid-cols-2">
          <div className="flex flex-col gap-0.5 border-border/50 border-r border-b pt-1 pr-5 pb-4">
            <span className="text-muted-foreground text-xs">High (&gt;0.8)</span>
            <span className="font-medium tabular-nums text-sm">4,969</span>
          </div>
          <div className="flex flex-col gap-0.5 border-border/50 border-b pt-1 pb-4 pl-5">
            <span className="text-muted-foreground text-xs">Medium (0.6–0.8)</span>
            <span className="font-medium tabular-nums text-sm">500</span>
          </div>
          <div className="flex flex-col gap-0.5 border-border/50 border-r pt-4 pr-5 pb-1">
            <span className="text-muted-foreground text-xs">Avg Score</span>
            <span className="font-medium tabular-nums text-sm">0.842</span>
          </div>
          <div className="flex flex-col gap-0.5 pt-4 pb-1 pl-5">
            <span className="text-muted-foreground text-xs">Total</span>
            <span className="font-medium tabular-nums text-sm">5,524</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
