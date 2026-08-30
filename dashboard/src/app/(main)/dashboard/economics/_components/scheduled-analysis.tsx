import { ClipboardCheck, FileText, RefreshCw, Zap } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const items = [
  {
    id: 1,
    title: "Cluster re-scan",
    date: "Due in 2h • Automated",
    icon: RefreshCw,
  },
  {
    id: 2,
    title: "Weekly validation report",
    date: "Due Aug 31 • Slurm + K8s",
    icon: FileText,
  },
  {
    id: 3,
    title: "Manual review checkpoint",
    date: "Due Sep 5 • Top 20 findings",
    icon: ClipboardCheck,
  },
];

export function ScheduledAnalysis() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-normal">Scheduled Analysis</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="flex items-baseline text-3xl leading-none tracking-tight">
              <span className="font-normal">3</span>
              <span className="text-muted-foreground text-xl ml-2 text-base">upcoming</span>
            </h2>
            <p className="text-muted-foreground text-sm leading-none">
              Next run analyzes <span className="font-medium text-foreground">50,000</span> jobs
            </p>
          </div>
          <div className="flex w-max items-center gap-2 rounded-md border border-border bg-muted/70 px-2 py-1.5 text-sm">
            <Zap className="size-4 fill-primary text-primary" />
            <span className="text-muted-foreground">
              Next automated scan will analyze <span className="font-medium text-foreground">50,000 jobs</span>
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <div key={item.id} className="flex items-center gap-3 rounded-md border border-border p-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-md border bg-background">
                <item.icon className="size-4 text-muted-foreground" />
              </div>
              <div className="flex flex-col gap-0.5 min-w-0">
                <p className="font-medium text-sm leading-none">{item.title}</p>
                <p className="text-muted-foreground text-xs">{item.date}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
