import { Ellipsis } from "lucide-react";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const findings: { type: string; count: string; avgValue: string; recovery: string }[] = [];

export function TopFindings() {
  return (
    <Card className="h-full gap-2">
      <CardHeader>
        <CardTitle className="font-normal">Top Findings by Value</CardTitle>
        <CardAction><Ellipsis className="size-4" /></CardAction>
      </CardHeader>
      <CardContent className="px-0">
        <Table className="[&_td:first-child]:pl-4 [&_td:last-child]:pr-4 [&_th:first-child]:pl-4 [&_th:last-child]:pr-4">
          <TableHeader className="[&_tr]:border-border/50">
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-8">Finding Type</TableHead>
              <TableHead className="h-8 w-20 text-right font-normal">Findings</TableHead>
              <TableHead className="h-8 w-28 text-right font-normal">Avg Value</TableHead>
              <TableHead className="h-8 w-24 text-right font-normal">Recovery %</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody className="[&_tr]:border-border/50">
            {findings.map((row) => (
              <TableRow className="hover:bg-transparent" key={row.type}>
                <TableCell className="max-w-0 truncate py-4 font-medium font-mono text-xs">{row.type}</TableCell>
                <TableCell className="text-right tabular-nums">{row.count}</TableCell>
                <TableCell className="text-right text-muted-foreground tabular-nums">{row.avgValue}</TableCell>
                <TableCell className="text-right text-muted-foreground tabular-nums">{row.recovery}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
