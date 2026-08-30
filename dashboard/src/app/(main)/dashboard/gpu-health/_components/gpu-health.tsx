"use client";
import { Fragment, useState } from "react";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import type { GpuRecord } from "./data";
import { GpuCard } from "./gpu-card";
import { GpuWaveform } from "./gpu-waveform";
import type { GpuSignalKind } from "./use-gpu-vital-series";
import { useGpuWaveformSeries } from "./use-gpu-vital-series";

interface GpuHealthProps {
  gpus: GpuRecord[];
}

const signalLabels: Record<GpuSignalKind, string> = {
  sm_utilization: "SM Utilization %",
  temperature: "Temperature °C",
  memory_bandwidth: "Mem BW %",
  power_draw: "Power W",
};

const vitalSignals: GpuSignalKind[] = ["sm_utilization", "temperature", "memory_bandwidth", "power_draw"];

function GpuVitalRow({ gpu, kind }: { gpu: GpuRecord; kind: GpuSignalKind }) {
  const series = useGpuWaveformSeries({ kind, gpu });
  return (
    <div className="grid grid-cols-[8rem_1fr] items-center gap-2 border-b border-border/50 py-1 last:border-0">
      <span className="text-muted-foreground text-xs tabular-nums">{signalLabels[kind]}</span>
      <GpuWaveform {...series} kind={kind} />
    </div>
  );
}

export function GpuHealth({ gpus }: GpuHealthProps) {
  const [selectedGpuId, setSelectedGpuId] = useState(gpus[0]?.id ?? "");
  const [acknowledgedIds, setAcknowledgedIds] = useState<string[]>([]);
  const selectedGpu = gpus.find((g) => g.id === selectedGpuId) ?? gpus[0];
  if (!selectedGpu) return null;

  const acknowledged = acknowledgedIds.includes(selectedGpu.id);
  const hasActiveAlarm = selectedGpu.status !== "healthy" && selectedGpu.alarm !== null && !acknowledged;

  function acknowledge(id: string) {
    setAcknowledgedIds((cur) => (cur.includes(id) ? cur : [...cur, id]));
  }

  const recentEvents = [
    { time: "04:12", label: "SM utilization dropped below 5%" },
    { time: "03:58", label: "Finding FND-0001 generated" },
    { time: "03:30", label: "Memory bandwidth normal" },
    { time: "02:15", label: "Job allocated to GPU" },
  ];

  return (
    <div className="grid min-w-0 flex-1 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="grid grid-cols-2 content-start *:border-border *:border-r *:border-b *:even:border-r-0">
        {gpus.map((gpu) => (
          <GpuCard key={gpu.id} gpu={gpu} active={gpu.id === selectedGpu.id} onSelect={setSelectedGpuId} />
        ))}
      </div>

      <div className="flex min-w-0 flex-col border-border lg:border-l">
        <div className="flex min-h-11 items-center gap-4 bg-muted/50 px-3">
          <div className="flex items-center gap-3 font-medium">
            <Badge className="rounded-none" variant="outline">{selectedGpu.id}</Badge>
            <span className="text-lg">{selectedGpu.model}</span>
          </div>
          <div className="text-muted-foreground text-sm">
            {selectedGpu.node} · {selectedGpu.cluster}
          </div>
        </div>
        <Separator />

        {selectedGpu.alarm && (
          <Alert
            className={cn(
              "min-h-9 rounded-none border-x-0 border-t-0 pr-32",
              hasActiveAlarm
                ? "border-amber-500 bg-amber-400 text-amber-950"
                : "border-border bg-muted text-foreground",
            )}
            variant="default"
          >
            <AlertTitle>{selectedGpu.alarm}</AlertTitle>
            {selectedGpu.alarmDuration && (
              <AlertDescription className={cn(hasActiveAlarm && "text-amber-950")}>
                Active for {selectedGpu.alarmDuration}
              </AlertDescription>
            )}
            <AlertAction className="top-1/2 -translate-y-1/2">
              <Button
                className="rounded-none"
                disabled={acknowledged}
                onClick={() => acknowledge(selectedGpu.id)}
                size="sm"
                variant="secondary"
              >
                {acknowledged ? "Acknowledged" : "Acknowledge"}
              </Button>
            </AlertAction>
          </Alert>
        )}

        <div className="grid grid-cols-4 gap-3 border-b border-border/50 p-3">
          {(["sm_utilization", "temperature", "memory_bandwidth", "power_draw"] as const).map((key) => {
            const valMap: Record<string, string> = {
              sm_utilization: `${selectedGpu.smUtil}%`,
              temperature: `${selectedGpu.tempC}°C`,
              memory_bandwidth: `${selectedGpu.memUsedGb}/${selectedGpu.memTotalGb}GB`,
              power_draw: `${selectedGpu.powerW}W`,
            };
            return (
              <div key={key} className="flex flex-col gap-0.5">
                <span className="text-muted-foreground text-xs">{signalLabels[key]}</span>
                <span className="font-semibold tabular-nums">{valMap[key]}</span>
              </div>
            );
          })}
        </div>

        <Tabs className="min-h-0 flex-1 gap-0" defaultValue="vitals">
          <TabsList
            className="w-full justify-start gap-0 border-b p-0 *:h-full *:max-w-32 *:rounded-none *:border-0 *:border-border *:border-r *:after:-bottom-px!"
            variant="line"
          >
            <TabsTrigger value="vitals">Vitals</TabsTrigger>
            <TabsTrigger value="events">Events</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
            <TabsTrigger value="info">Info</TabsTrigger>
          </TabsList>

          <TabsContent className="m-0 px-4 py-2" value="vitals">
            {vitalSignals.map((kind) => (
              <GpuVitalRow key={kind} gpu={selectedGpu} kind={kind} />
            ))}
          </TabsContent>

          <TabsContent className="m-0" value="events">
            <div className="min-h-44">
              <div className="grid grid-cols-[4rem_1fr] bg-muted/40 px-4 py-2 font-medium text-muted-foreground text-xs">
                <span>Time</span>
                <span>Event</span>
              </div>
              <Separator />
              {recentEvents.map((event, index) => (
                <Fragment key={`${event.time}-${event.label}`}>
                  <div className="grid min-h-11 grid-cols-[4rem_1fr] items-center px-4 py-2 text-sm">
                    <span className="text-muted-foreground tabular-nums">{event.time}</span>
                    <span>{event.label}</span>
                  </div>
                  {index < recentEvents.length - 1 && <Separator />}
                </Fragment>
              ))}
            </div>
          </TabsContent>

          <TabsContent className="m-0 flex flex-col items-center justify-center gap-1 px-4 py-8 text-center" value="history">
            <p className="font-medium text-sm">Historical trends active</p>
            <p className="text-muted-foreground text-xs">24h utilization history available for this GPU.</p>
          </TabsContent>

          <TabsContent className="m-0 px-4 py-4" value="info">
            <div className="grid gap-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">GPU ID</span><span className="font-mono">{selectedGpu.id}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Model</span><span>{selectedGpu.model}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Node</span><span className="font-mono">{selectedGpu.node}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Cluster</span><span className="font-mono">{selectedGpu.cluster}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Memory</span><span>{selectedGpu.memTotalGb}GB</span></div>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
