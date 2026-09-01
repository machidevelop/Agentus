import { Cpu, Clock } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function WasteBreakdown() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
              <Cpu className="size-4" />
            </div>
            Utilization Waste
          </CardTitle>
          <CardDescription>GPU-hours wasted vs recovered</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4">
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground text-sm">Wasted GPU-hours</span>
              <span className="font-medium text-2xl tabular-nums">0</span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground text-sm">Recovered GPU-hours</span>
              <span className="font-medium text-2xl tabular-nums text-primary">0</span>
            </div>
            <div className="border-t pt-4">
              <div className="flex items-baseline justify-between">
                <span className="text-muted-foreground text-sm">Monthly value</span>
                <span className="font-medium text-2xl tabular-nums">$0</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
              <Clock className="size-4" />
            </div>
            Queue Waste
          </CardTitle>
          <CardDescription>Wait time eliminated by reordering</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4">
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground text-sm">Deduped wait-hours</span>
              <span className="font-medium text-2xl tabular-nums">0</span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-muted-foreground text-sm">Queue findings</span>
              <span className="font-medium text-2xl tabular-nums text-primary">0</span>
            </div>
            <div className="border-t pt-4">
              <div className="flex items-baseline justify-between">
                <span className="text-muted-foreground text-sm">Monthly value</span>
                <span className="font-medium text-2xl tabular-nums">$0</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
