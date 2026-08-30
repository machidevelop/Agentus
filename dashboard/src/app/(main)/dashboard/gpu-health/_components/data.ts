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

export const gpus: GpuRecord[] = [
  { id: "GPU-001", node: "node-aws-01", cluster: "aws-us-east-1", model: "A100-80GB", status: "healthy", smUtil: 78, tempC: 72, memUsedGb: 52, memTotalGb: 80, powerW: 280, alarm: null, alarmDuration: null, phase: 0.0 },
  { id: "GPU-002", node: "node-aws-01", cluster: "aws-us-east-1", model: "A100-80GB", status: "healthy", smUtil: 81, tempC: 74, memUsedGb: 60, memTotalGb: 80, powerW: 295, alarm: null, alarmDuration: null, phase: 0.1 },
  { id: "GPU-003", node: "node-aws-02", cluster: "aws-us-east-1", model: "A100-80GB", status: "warning", smUtil: 12, tempC: 45, memUsedGb: 8, memTotalGb: 80, powerW: 90, alarm: "Low utilization: 12% SM activity for 3.2h", alarmDuration: "3h 12m", phase: 0.2 },
  { id: "GPU-004", node: "node-aws-02", cluster: "aws-us-east-1", model: "A100-80GB", status: "healthy", smUtil: 91, tempC: 78, memUsedGb: 72, memTotalGb: 80, powerW: 320, alarm: null, alarmDuration: null, phase: 0.3 },
  { id: "GPU-005", node: "node-aws-03", cluster: "aws-us-east-1", model: "A100-80GB", status: "critical", smUtil: 0, tempC: 38, memUsedGb: 0, memTotalGb: 80, powerW: 55, alarm: "GPU idle for 6.8h — job holding allocation with no kernel launches", alarmDuration: "6h 48m", phase: 0.4 },
  { id: "GPU-006", node: "node-aws-03", cluster: "aws-us-east-1", model: "A100-80GB", status: "critical", smUtil: 0, tempC: 39, memUsedGb: 0, memTotalGb: 80, powerW: 57, alarm: "GPU idle for 6.8h — same job as GPU-005", alarmDuration: "6h 48m", phase: 0.5 },
  { id: "GPU-007", node: "node-aws-04", cluster: "aws-us-east-1", model: "A100-80GB", status: "healthy", smUtil: 65, tempC: 68, memUsedGb: 44, memTotalGb: 80, powerW: 245, alarm: null, alarmDuration: null, phase: 0.6 },
  { id: "GPU-008", node: "node-aws-04", cluster: "aws-us-east-1", model: "A100-80GB", status: "idle", smUtil: 0, tempC: 34, memUsedGb: 0, memTotalGb: 80, powerW: 48, alarm: null, alarmDuration: null, phase: 0.7 },
  { id: "GPU-009", node: "node-gcp-01", cluster: "gcp-europe-west4", model: "H100-SXM5", status: "healthy", smUtil: 62, tempC: 65, memUsedGb: 50, memTotalGb: 80, powerW: 410, alarm: null, alarmDuration: null, phase: 0.15 },
  { id: "GPU-010", node: "node-gcp-01", cluster: "gcp-europe-west4", model: "H100-SXM5", status: "healthy", smUtil: 58, tempC: 63, memUsedGb: 46, memTotalGb: 80, powerW: 395, alarm: null, alarmDuration: null, phase: 0.25 },
  { id: "GPU-011", node: "node-gcp-02", cluster: "gcp-europe-west4", model: "H100-SXM5", status: "warning", smUtil: 22, tempC: 50, memUsedGb: 18, memTotalGb: 80, powerW: 160, alarm: "Low SM utilization: 22% for 1.8h — potential data loading stall", alarmDuration: "1h 48m", phase: 0.35 },
  { id: "GPU-012", node: "node-gcp-02", cluster: "gcp-europe-west4", model: "H100-SXM5", status: "healthy", smUtil: 77, tempC: 71, memUsedGb: 62, memTotalGb: 80, powerW: 460, alarm: null, alarmDuration: null, phase: 0.45 },
  { id: "GPU-013", node: "node-az-01", cluster: "azure-eastus", model: "A100-80GB", status: "warning", smUtil: 18, tempC: 48, memUsedGb: 12, memTotalGb: 80, powerW: 110, alarm: "Utilization drop: 18% SM for 2.1h", alarmDuration: "2h 6m", phase: 0.55 },
  { id: "GPU-014", node: "node-az-01", cluster: "azure-eastus", model: "A100-80GB", status: "healthy", smUtil: 85, tempC: 76, memUsedGb: 68, memTotalGb: 80, powerW: 302, alarm: null, alarmDuration: null, phase: 0.65 },
  { id: "GPU-015", node: "node-op-01", cluster: "on-prem-dc1", model: "A100-40GB", status: "healthy", smUtil: 48, tempC: 60, memUsedGb: 28, memTotalGb: 40, powerW: 195, alarm: null, alarmDuration: null, phase: 0.75 },
  { id: "GPU-016", node: "node-op-01", cluster: "on-prem-dc1", model: "A100-40GB", status: "idle", smUtil: 0, tempC: 32, memUsedGb: 0, memTotalGb: 40, powerW: 42, alarm: null, alarmDuration: null, phase: 0.85 },
];
