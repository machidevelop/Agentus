export type GpuStatus = "healthy" | "warning" | "critical" | "idle";
export type GpuModel = "A100-80GB" | "H100-SXM5" | "A100-40GB";

export interface GpuRecord {
  id: string;
  node: string;
  cluster: string;
  model: GpuModel;
  status: GpuStatus;
  smUtil: number;
  tempC: number;
  memUsedGb: number;
  memTotalGb: number;
  powerW: number;
  alarm: string | null;
  alarmDuration: string | null;
  phase: number;
}

export const gpus: GpuRecord[] = [];
