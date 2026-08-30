import { useMemo } from "react";

import type { GpuRecord } from "./data";
import { WAVEFORM_TICK_INTERVAL_MS, useWaveformTick } from "./use-realtime-tick";

export type GpuSignalKind = "sm_utilization" | "temperature" | "memory_bandwidth" | "power_draw";

export interface SignalPoint {
  value: number;
}

const SAMPLE_STEP_SECONDS = 0.025;

function generateSignal(kind: GpuSignalKind, gpu: GpuRecord, time: number): number {
  const { phase } = gpu;
  const t = time + phase * 10;

  switch (kind) {
    case "sm_utilization": {
      const base = gpu.smUtil;
      const noise = Math.sin(t * 0.8) * 8 + Math.sin(t * 2.3 + 1) * 4 + Math.sin(t * 5.1) * 2;
      return Math.max(0, Math.min(100, base + noise));
    }
    case "temperature": {
      const base = gpu.tempC;
      const drift = Math.sin(t * 0.1) * 3 + Math.sin(t * 0.4) * 1.5;
      return Math.max(20, Math.min(95, base + drift));
    }
    case "memory_bandwidth": {
      const base = (gpu.memUsedGb / gpu.memTotalGb) * 100;
      const noise = Math.sin(t * 1.2 + 0.5) * 10 + Math.sin(t * 3.7) * 5;
      return Math.max(0, Math.min(100, base + noise));
    }
    case "power_draw": {
      const base = gpu.powerW;
      const noise = Math.sin(t * 0.6 + 1.2) * 20 + Math.sin(t * 1.8) * 10;
      return Math.max(0, Math.min(400, base + noise));
    }
    default:
      return 0;
  }
}

function getSignalDomain(kind: GpuSignalKind): [number, number] {
  switch (kind) {
    case "sm_utilization": return [0, 100];
    case "temperature": return [20, 100];
    case "memory_bandwidth": return [0, 100];
    case "power_draw": return [0, 400];
  }
}

function createSignalWindow(gpu: GpuRecord, kind: GpuSignalKind, sampleCount: number, endTime: number): SignalPoint[] {
  return Array.from({ length: sampleCount }, (_, index) => {
    const time = endTime - (sampleCount - index - 1) * SAMPLE_STEP_SECONDS;
    return { value: generateSignal(kind, gpu, time) };
  });
}

interface GpuWaveformSeriesOptions {
  compact?: boolean;
  kind: GpuSignalKind;
  gpu: GpuRecord;
}

export function useGpuWaveformSeries({ compact = false, kind, gpu }: GpuWaveformSeriesOptions) {
  const tick = useWaveformTick();
  const sampleCount = compact ? 160 : 400;
  const data = useMemo(
    () => createSignalWindow(gpu, kind, sampleCount, (tick * WAVEFORM_TICK_INTERVAL_MS) / 1000),
    [kind, gpu, sampleCount, tick],
  );
  return { ariaLabel: `${gpu.id} ${kind} waveform`, data, domain: getSignalDomain(kind) };
}
