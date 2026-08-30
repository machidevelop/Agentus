"use client";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { GpuRecord, GpuStatus } from "./data";
import { GpuWaveform } from "./gpu-waveform";
import { useGpuWaveformSeries } from "./use-gpu-vital-series";

interface GpuCardProps {
  gpu: GpuRecord;
  active: boolean;
  onSelect: (id: string) => void;
}

const statusStyles: Record<GpuStatus, string> = {
  healthy: "border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300",
  warning: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  critical: "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300",
  idle: "border-gray-400/20 bg-gray-400/10 text-gray-600 dark:text-gray-400",
};

function GpuCardWaveform({ gpu }: { gpu: GpuRecord }) {
  const series = useGpuWaveformSeries({ compact: true, kind: "sm_utilization", gpu });
  return <GpuWaveform {...series} kind="sm_utilization" compact />;
}

export function GpuCard({ gpu, active, onSelect }: GpuCardProps) {
  return (
    <button
      className={cn(
        "flex min-h-0 flex-col gap-1.5 p-2 text-left transition-colors",
        active && "bg-muted/50",
        "hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
      )}
      onClick={() => onSelect(gpu.id)}
      type="button"
    >
      <div className="flex items-start justify-between gap-1">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono font-semibold text-xs leading-none">{gpu.id}</span>
          <span className="text-muted-foreground text-[10px]">{gpu.node}</span>
        </div>
        <Badge variant="outline" className={cn("rounded-sm px-1.5 py-0.5 text-[9px] font-medium uppercase", statusStyles[gpu.status])}>
          {gpu.status}
        </Badge>
      </div>
      <GpuCardWaveform gpu={gpu} />
      <div className="grid grid-cols-3 gap-1 text-[10px]">
        <div className="flex flex-col gap-0.5">
          <span className="text-muted-foreground">SM</span>
          <span className="tabular-nums font-medium">{gpu.smUtil}%</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-muted-foreground">Temp</span>
          <span className="tabular-nums font-medium">{gpu.tempC}°C</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-muted-foreground">Mem</span>
          <span className="tabular-nums font-medium">{gpu.memUsedGb}/{gpu.memTotalGb}G</span>
        </div>
      </div>
    </button>
  );
}
