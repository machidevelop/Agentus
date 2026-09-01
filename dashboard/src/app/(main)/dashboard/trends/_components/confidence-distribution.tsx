"use client";

import { Ellipsis } from "lucide-react";
import { Bar, BarChart, type BarShapeProps, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const confidenceData = Array.from({ length: 30 }, (_, i) => ({ bucket: i + 1, count: 0 }));

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
            <span className="text-2xl tabular-nums leading-none tracking-tight">0%</span>
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
            <span className="font-medium tabular-nums text-sm">0</span>
          </div>
          <div className="flex flex-col gap-0.5 border-border/50 border-b pt-1 pb-4 pl-5">
            <span className="text-muted-foreground text-xs">Medium (0.6–0.8)</span>
            <span className="font-medium tabular-nums text-sm">0</span>
          </div>
          <div className="flex flex-col gap-0.5 border-border/50 border-r pt-4 pr-5 pb-1">
            <span className="text-muted-foreground text-xs">Avg Score</span>
            <span className="font-medium tabular-nums text-sm">0</span>
          </div>
          <div className="flex flex-col gap-0.5 pt-4 pb-1 pl-5">
            <span className="text-muted-foreground text-xs">Total</span>
            <span className="font-medium tabular-nums text-sm">0</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
