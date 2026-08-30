import { ChevronRight, Server, Zap } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from "@/components/ui/item";

const charges = [
  { id: 1, title: "AWS GPU Billing Cycle", date: "Aug 31, 2026 · $89,344", autopay: true },
  { id: 2, title: "GCP GPU Billing", date: "Sep 01, 2026 · $104,192", autopay: true },
  { id: 3, title: "Azure EA Agreement", date: "Sep 05, 2026 · $22,336", autopay: false },
  { id: 4, title: "Reserved Capacity Renewal", date: "Sep 15, 2026 · $45,000", autopay: false },
];

export function UpcomingCharges() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Upcoming Charges</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="flex items-baseline text-3xl leading-none tracking-tight">
              <span className="font-normal">$260</span>
              <span className="text-muted-foreground text-xl">,872</span>
            </h2>
            <p className="text-muted-foreground text-sm leading-none">
              You have <span className="font-medium text-foreground">4</span> charges due this month
            </p>
          </div>
          <div className="flex w-max items-center gap-2 rounded-md border border-border bg-muted/70 px-2 py-1.5 text-sm">
            <Zap className="size-4 fill-primary text-primary" />
            <span className="text-muted-foreground">
              Autopay will process <span className="font-medium text-foreground">$193,536</span> this week
            </span>
          </div>
        </div>

        <ItemGroup>
          {charges.map((charge) => (
            <Item key={charge.id} variant="outline" size="xs">
              <ItemMedia>
                <div className="grid size-9 place-items-center rounded-md border bg-background">
                  <Server className="size-4 text-muted-foreground" />
                </div>
              </ItemMedia>
              <ItemContent>
                <ItemTitle className="flex items-center gap-1.5">
                  {charge.title}
                  {charge.autopay && <Zap className="size-3 fill-primary text-primary" />}
                </ItemTitle>
                <ItemDescription>{charge.date}</ItemDescription>
              </ItemContent>
              <ItemActions>
                <ChevronRight className="size-5 text-muted-foreground" />
              </ItemActions>
            </Item>
          ))}
        </ItemGroup>
      </CardContent>
    </Card>
  );
}
