import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export function CostBreakdown() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Waste breakdown</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-1 md:grid-cols-3">
        <section className="isolate flex gap-[0.5px]">
          <Separator orientation="vertical" className="mb-1 h-auto self-auto border-muted-foreground/50 border-l border-dashed bg-transparent" />
          <div className="flex min-h-24 flex-1 flex-col justify-between">
            <div className="flex min-w-0 flex-col gap-1 px-1">
              <p className="wrap-break-word text-muted-foreground text-xs leading-none">Idle Allocation · 40.7%</p>
              <div className="text-lg leading-none tracking-tight">$218,000</div>
            </div>
            <div className="-ml-0.5 h-5 rounded-sm bg-chart-1" />
          </div>
        </section>
        <section className="isolate flex gap-[0.5px]">
          <Separator orientation="vertical" className="mb-1 h-auto self-auto border-muted-foreground/50 border-l border-dashed bg-transparent" />
          <div className="flex min-h-24 flex-1 flex-col justify-between">
            <div className="flex min-w-0 flex-col gap-1 px-1">
              <p className="wrap-break-word text-muted-foreground text-xs leading-none">Queue Inefficiency · 29.1%</p>
              <div className="text-lg leading-none tracking-tight">$156,000</div>
            </div>
            <div className="-ml-0.5 h-5 rounded-sm bg-chart-1/75" />
          </div>
        </section>
        <section className="isolate flex gap-[0.5px]">
          <Separator orientation="vertical" className="mb-1 h-auto self-auto border-muted-foreground/50 border-l border-dashed bg-transparent" />
          <div className="flex min-h-24 flex-1 flex-col justify-between">
            <div className="flex min-w-0 flex-col gap-1 px-1">
              <p className="wrap-break-word text-muted-foreground text-xs leading-none">Over-Allocation · 18.1%</p>
              <div className="text-lg leading-none tracking-tight">$97,000</div>
            </div>
            <div className="-ml-0.5 h-5 rounded-sm bg-chart-1/50" />
          </div>
        </section>
      </CardContent>
    </Card>
  );
}
