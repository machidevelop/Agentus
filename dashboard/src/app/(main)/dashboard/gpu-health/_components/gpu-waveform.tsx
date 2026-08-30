import { Line, LineChart, YAxis } from "recharts";

import { type ChartConfig, ChartContainer } from "@/components/ui/chart";
import { cn } from "@/lib/utils";

import type { GpuSignalKind, SignalPoint } from "./use-gpu-vital-series";

interface GpuWaveformProps {
  ariaLabel: string;
  compact?: boolean;
  data: SignalPoint[];
  domain: [number, number];
  kind: GpuSignalKind;
}

const waveformChartConfig = {
  signal: { label: "Signal", color: "currentColor" },
} satisfies ChartConfig;

const waveformClasses: Record<GpuSignalKind, string> = {
  sm_utilization: "text-lime-500 dark:text-lime-400",
  temperature: "text-red-500 dark:text-red-400",
  memory_bandwidth: "text-cyan-500 dark:text-cyan-400",
  power_draw: "text-amber-500 dark:text-amber-400",
};

export function GpuWaveform({ ariaLabel, compact = false, data, domain, kind }: GpuWaveformProps) {
  return (
    <ChartContainer
      aria-label={ariaLabel}
      className={cn("aspect-auto w-full", compact ? "h-9" : "h-full min-h-16", waveformClasses[kind])}
      config={waveformChartConfig}
      initialDimension={compact ? { width: 280, height: 36 } : { width: 800, height: 64 }}
      role="img"
    >
      <LineChart accessibilityLayer data={data} margin={{ bottom: 0, left: 0, right: 0, top: 0 }}>
        <YAxis allowDataOverflow domain={domain} hide width={0} />
        <Line
          dataKey="value"
          dot={false}
          isAnimationActive={false}
          stroke="var(--color-signal)"
          strokeWidth={compact ? 1.25 : 1.5}
          type="monotoneX"
        />
      </LineChart>
    </ChartContainer>
  );
}
