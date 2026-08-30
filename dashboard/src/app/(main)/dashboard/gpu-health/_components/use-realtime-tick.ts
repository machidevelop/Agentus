import { useSyncExternalStore } from "react";

import { createRealtimeTicker, MONITORING_SPEED } from "./realtime-utils";

export const WAVEFORM_TICK_INTERVAL_MS = 100;

const getInitialTick = () => 0;
const monitoringSpeed = Math.max(MONITORING_SPEED, 0);
const waveformTicker = createRealtimeTicker(WAVEFORM_TICK_INTERVAL_MS);
const trendTicker = createRealtimeTicker(1000);

export function useWaveformTick() {
  return useSyncExternalStore(waveformTicker.subscribe, waveformTicker.getSnapshot, getInitialTick) * monitoringSpeed;
}

export function useTrendTick() {
  return Math.floor(
    useSyncExternalStore(trendTicker.subscribe, trendTicker.getSnapshot, getInitialTick) * monitoringSpeed,
  );
}
