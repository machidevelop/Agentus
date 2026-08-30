import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export function IncomeBreakdown() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Value Sources</CardTitle>
      </CardHeader>

      <CardContent className="grid grid-cols-1 gap-1 md:grid-cols-3">
        <section className="isolate flex gap-[0.5px]">
          <Separator
            orientation="vertical"
            className="mb-1 h-auto self-auto border-muted-foreground/50 border-l border-dashed bg-transparent"
          />
          <div className="flex min-h-24 flex-1 flex-col justify-between">
            <div className="flex min-w-0 flex-col gap-1 px-1">
              <p className="wrap-break-word text-muted-foreground text-xs leading-none">Idle Allocation · 82%</p>
              <div className="text-lg leading-none tracking-tight">$438,051</div>
              <p className="text-muted-foreground text-xs">2,088 findings</p>
            </div>
            <div className="-ml-0.5 h-5 rounded-sm bg-chart-3" />
          </div>
        </section>

        <section className="isolate flex gap-[0.5px]">
          <Separator
            orientation="vertical"
            className="mb-1 h-auto self-auto border-muted-foreground/50 border-l border-dashed bg-transparent"
          />
          <div className="flex min-h-24 flex-1 flex-col justify-between">
            <div className="flex min-w-0 flex-col gap-1 px-1">
              <p className="wrap-break-word text-muted-foreground text-xs leading-none">Queue Inefficiency · 10%</p>
              <div className="text-lg leading-none tracking-tight">$53,519</div>
              <p className="text-muted-foreground text-xs">269 findings</p>
            </div>
            <div className="-ml-0.5 h-5 rounded-sm bg-chart-3/75" />
          </div>
        </section>

        <section className="isolate flex gap-[0.5px]">
          <Separator
            orientation="vertical"
            className="mb-1 h-auto self-auto border-muted-foreground/50 border-l border-dashed bg-transparent"
          />
          <div className="flex min-h-24 flex-1 flex-col justify-between">
            <div className="flex min-w-0 flex-col gap-1 px-1">
              <p className="wrap-break-word text-muted-foreground text-xs leading-none">Over-Allocation + Frag · 8%</p>
              <div className="text-lg leading-none tracking-tight">$43,615</div>
              <p className="text-muted-foreground text-xs">201 findings</p>
            </div>
            <div className="-ml-0.5 h-5 rounded-sm bg-chart-3/50" />
          </div>
        </section>
      </CardContent>
    </Card>
  );
}
