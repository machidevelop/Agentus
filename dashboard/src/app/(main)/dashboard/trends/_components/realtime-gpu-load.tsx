"use client";
import { Ellipsis } from "lucide-react";
import { Bar, BarChart, type BarShapeProps, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

const realtimeData = Array.from({ length: 30 }, (_, i) => ({ slot: i + 1, util: 0 }));

const chartConfig = {
  util: { color: "var(--chart-3)", label: "GPU Load %" },
} satisfies ChartConfig;

function RealtimeBarShape(props: BarShapeProps) {
  const { height, payload, width, x, y } = props;
  const barPayload = payload as (typeof realtimeData)[number] | undefined;
  const barHeightValue = Number(height);
  const barWidthValue = Number(width);
  const xValue = Number(x);
  const yValue = Number(y);
  const util = barPayload?.util ?? 0;
  const fill = "var(--color-util)";
  const fillOpacity = util >= 75 ? 0.95 : 0.4;
  const baselineFill = util === 0 ? "var(--destructive)" : fill;
  const baselineOpacity = util === 0 ? 1 : fillOpacity;
  const baselineY = yValue + barHeightValue - 2;
  const barGap = 4;
  const barHeight = Math.max(0, barHeightValue - barGap);

  return (
    <g>
      <rect x={xValue} y={baselineY} width={barWidthValue} height={2} rx={1} fill={baselineFill} fillOpacity={baselineOpacity} />
      {util > 0 && barHeight > 0 ? (
        <rect x={xValue} y={yValue} width={barWidthValue} height={barHeight} rx={2} fill={fill} fillOpacity={fillOpacity} />
      ) : null}
    </g>
  );
}

const clusters: { name: string; util: number }[] = [];

export function RealtimeGpuLoad() {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="font-normal">Realtime GPU Load</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-end justify-between">
          <div className="flex items-baseline gap-1">
            <span className="text-2xl tabular-nums leading-none tracking-tight">0</span>
            <span className="text-muted-foreground text-sm">% avg utilization</span>
          </div>
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-green-500 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-green-500" />
            </span>
            <span>Live</span>
          </div>
        </div>
        <ChartContainer config={chartConfig} className="h-36 w-full">
          <BarChart data={realtimeData} margin={{ bottom: 0, left: 0, right: 0, top: 0 }} barCategoryGap={3}>
            <XAxis dataKey="slot" hide />
            <YAxis hide domain={[0, 100]} />
            <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="util" fill="var(--color-util)" shape={RealtimeBarShape} />
          </BarChart>
        </ChartContainer>
        <div className="grid grid-cols-2">
          {clusters.map((c, i) => (
            <div
              key={c.name}
              className={`flex items-center gap-3 pt-1 pb-4 ${i % 2 === 0 ? "pr-5 border-r" : "pl-5"} ${i < 2 ? "border-b" : ""} border-border/50`}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-muted-foreground">{c.name}</div>
              </div>
              <span className="text-sm tabular-nums">{c.util}%</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
