import { Ellipsis } from "lucide-react";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const clusters = [
  { name: "aws-us-east-1", gpus: 256, utilization: "73%", findings: "1,284", waste: "$218k/mo" },
  { name: "gcp-europe-west4", gpus: 128, utilization: "58%", findings: "621", waste: "$156k/mo" },
  { name: "azure-eastus", gpus: 64, utilization: "81%", findings: "412", waste: "$97k/mo" },
  { name: "on-prem-dc1", gpus: 64, utilization: "42%", findings: "241", waste: "$64k/mo" },
];

export function TopClusters() {
  return (
    <Card className="h-full gap-2">
      <CardHeader>
        <CardTitle className="font-normal">Cluster Performance</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent className="px-0">
        <Table className="[&_td:first-child]:pl-4 [&_td:last-child]:pr-4 [&_th:first-child]:pl-4 [&_th:last-child]:pr-4">
          <TableHeader className="[&_tr]:border-border/50">
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-8" />
              <TableHead className="h-8 w-16 text-right font-normal">GPUs</TableHead>
              <TableHead className="h-8 w-24 text-right font-normal">Util.</TableHead>
              <TableHead className="h-8 w-24 text-right font-normal">Findings</TableHead>
              <TableHead className="h-8 w-28 text-right font-normal">Waste/mo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="[&_tr]:border-border/50">
            {clusters.map((c) => (
              <TableRow className="hover:bg-transparent" key={c.name}>
                <TableCell className="max-w-0 truncate py-4 font-medium font-mono text-sm">{c.name}</TableCell>
                <TableCell className="text-right tabular-nums">{c.gpus}</TableCell>
                <TableCell className="text-right text-muted-foreground tabular-nums">{c.utilization}</TableCell>
                <TableCell className="text-right text-muted-foreground tabular-nums">{c.findings}</TableCell>
                <TableCell className="text-right tabular-nums">{c.waste}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
