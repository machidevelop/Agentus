import { format } from "date-fns";
import { Bell, Network, Printer, Volume2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { gpus } from "./_components/data";
import { GpuHealth } from "./_components/gpu-health";

export default function Page() {
  const now = new Date("2026-08-30T04:58:00");
  const alarmCount = gpus.filter((g) => g.alarm !== null).length;

  return (
    <div className="flex min-h-[calc(100svh-var(--dashboard-header-height))] min-w-0 flex-col" data-content-padding="false">
      <div className="grid min-h-10 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-2 py-2 text-sm lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:py-0">
        <div className="truncate lg:overflow-visible font-medium">GPU HEALTH MONITOR</div>
        <div className="flex items-center gap-3">
          <span className="whitespace-nowrap">{gpus.length} GPUs</span>
          {alarmCount > 0 && (
            <Badge variant="destructive" className="rounded-full gap-1">
              <Bell className="size-3" />
              {alarmCount} alerts
            </Badge>
          )}
        </div>
        <div className="col-span-2 flex items-center justify-between gap-5 text-muted-foreground lg:col-span-1 lg:justify-end">
          <span className="whitespace-nowrap tabular-nums">
            {format(now, "dd MMM yyyy")}&nbsp;&nbsp;{format(now, "HH:mm:ss")}
          </span>
          <Tooltip>
            <TooltipTrigger aria-label="Alert audio enabled" className="inline-flex" type="button">
              <Volume2 aria-hidden="true" className="size-4" />
            </TooltipTrigger>
            <TooltipContent>Alert audio enabled</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger aria-label="Monitoring network connected" className="inline-flex" type="button">
              <Network aria-hidden="true" className="size-4" />
            </TooltipTrigger>
            <TooltipContent>Monitoring network connected</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <Separator />

      <GpuHealth gpus={gpus} />

      <Separator />
      <footer className="flex flex-wrap gap-2 p-2 *:data-[slot=button]:h-11 *:data-[slot=button]:min-w-32 *:data-[slot=button]:flex-1 *:data-[slot=button]:rounded-none">
        <Button variant="outline">Overview</Button>
        <Button variant="outline">GPU Setup</Button>
        <Button variant="outline">Alert Review</Button>
        <Button variant="outline">Waveform Review</Button>
        <Button variant="outline">Export Health Report</Button>
        <Button variant="outline">
          <Printer data-icon="inline-start" />Print
        </Button>
        <Button variant="outline">
          <Volume2 data-icon="inline-start" />Silence
        </Button>
        <Badge className="h-11 min-w-44 flex-1 rounded-none text-muted-foreground" variant="outline">
          Monitoring cluster connected
        </Badge>
      </footer>
    </div>
  );
}
