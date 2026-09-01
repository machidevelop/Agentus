"use client";

import { Ellipsis } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, type LabelProps, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const chartConfig = {
  value: { color: "var(--chart-1)", label: "Count" },
} satisfies ChartConfig;

type RunDatum = { label: string; source: string; value: number };

const fiveKData: RunDatum[] = [];

const fiftyKData: RunDatum[] = [];

const byTypeData: RunDatum[] = [];

function renderValueLabel(props: LabelProps) {
  const { height, value, y } = props;
  return (
    <text className="fill-foreground" dominantBaseline="middle" dx={-6}
      fontSize={14} textAnchor="end" x="100%" y={Number(y) + Number(height) / 2}>
      {value}
    </text>
  );
}

function RunBarChart({ data }: { data: RunDatum[] }) {
  return (
    <ChartContainer config={chartConfig} className="h-64 w-full">
      <BarChart accessibilityLayer data={data} layout="vertical" margin={{ left: 0, right: 48 }}>
        <CartesianGrid horizontal={false} vertical={false} />
        <YAxis dataKey="source" hide tickLine={false} tickMargin={10} type="category" />
        <XAxis dataKey="value" hide type="number" />
        <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="line" />} />
        <Bar barSize={40} dataKey="value" fill="var(--color-value)" fillOpacity={0.5} radius={8}>
          <LabelList className="fill-foreground" dataKey="source" fontSize={14} offset={12} position="insideLeft" />
          <LabelList content={renderValueLabel} dataKey="label" />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

export function RunComparison() {
  return (
    <Card className="h-full gap-2">
      <CardHeader>
        <CardTitle className="font-normal">Run Comparison</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent className="px-0">
        <Tabs defaultValue="5k" className="flex flex-col gap-3">
          <TabsList className="w-full justify-start border-b px-2.5" variant="line">
            <TabsTrigger className="flex-none font-normal" value="5k">5k Deduped</TabsTrigger>
            <TabsTrigger className="flex-none font-normal" value="50k">50k Run</TabsTrigger>
            <TabsTrigger className="flex-none font-normal" value="by-type">By Type</TabsTrigger>
          </TabsList>
          <TabsContent value="5k" className="px-4"><RunBarChart data={fiveKData} /></TabsContent>
          <TabsContent value="50k" className="px-4"><RunBarChart data={fiftyKData} /></TabsContent>
          <TabsContent value="by-type" className="px-4"><RunBarChart data={byTypeData} /></TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
