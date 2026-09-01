import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { findingsSummaryData } from "./findings-summary-table/data";
import { FindingsSummaryTable } from "./findings-summary-table/table";

export function FindingsSummary() {
  return (
    <Card className="overflow-hidden p-0">
      <CardHeader className="p-5 pb-0">
        <div>
          <CardTitle>0 Findings</CardTitle>
          <CardDescription>Latest detected GPU waste findings across all clusters</CardDescription>
        </div>
        <CardAction>
          <Button variant="outline" size="sm">
            <Download className="mr-2 size-4" />
            Export
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="p-0">
        <FindingsSummaryTable data={findingsSummaryData} />
      </CardContent>
    </Card>
  );
}
