"use client";
import { Ellipsis } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, type LabelProps, XAxis, YAxis } from "recharts";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const chartConfig = {
  count: { color: "var(--chart-1)", label: "Findings" },
} satisfies ChartConfig;

type FindingDatum = { label: string; category: string; count: number };

const byType: FindingDatum[] = [];

const byCluster: FindingDatum[] = [];

const byTeam: FindingDatum[] = [];

function renderValueLabel(props: LabelProps) {
  const { height, value, y } = props;
  return (
    <text className="fill-foreground" dominantBaseline="middle" dx={-6} fontSize={14} textAnchor="end" x="100%" y={Number(y) + Number(height) / 2}>
      {value}
    </text>
  );
}

function FindingBarChart({ data }: { data: FindingDatum[] }) {
  return (
    <ChartContainer config={chartConfig} className="h-64 w-full">
      <BarChart accessibilityLayer data={data} layout="vertical" margin={{ left: 0, right: 48 }}>
        <CartesianGrid horizontal={false} vertical={false} />
        <YAxis dataKey="category" hide tickLine={false} tickMargin={10} type="category" />
        <XAxis dataKey="count" hide type="number" />
        <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="line" />} />
        <Bar barSize={40} dataKey="count" fill="var(--color-count)" fillOpacity={0.5} radius={8}>
          <LabelList className="fill-foreground" dataKey="category" fontSize={14} offset={12} position="insideLeft" />
          <LabelList content={renderValueLabel} dataKey="label" />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

export function TopFindingTypes() {
  return (
    <Card className="h-full gap-2">
      <CardHeader>
        <CardTitle className="font-normal">Finding Breakdown</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent className="px-0">
        <Tabs defaultValue="type" className="flex flex-col gap-3">
          <TabsList className="w-full justify-start border-b px-2.5" variant="line">
            <TabsTrigger className="flex-none font-normal" value="type">Type</TabsTrigger>
            <TabsTrigger className="flex-none font-normal" value="cluster">Cluster</TabsTrigger>
            <TabsTrigger className="flex-none font-normal" value="team">Team</TabsTrigger>
          </TabsList>
          <TabsContent value="type" className="px-4"><FindingBarChart data={byType} /></TabsContent>
          <TabsContent value="cluster" className="px-4"><FindingBarChart data={byCluster} /></TabsContent>
          <TabsContent value="team" className="px-4"><FindingBarChart data={byTeam} /></TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
