import type { Node, Edge } from "@xyflow/react";

export type AgentStatus = "active" | "paused" | "error";
export type AgentDomain =
  | "scheduling"
  | "storage"
  | "network"
  | "commitments"
  | "power"
  | "training"
  | "inference"
  | "coordination"
  | "custom";

export interface AgentConfig extends Record<string, unknown> {
  confidenceFloor: number;
  maxCandidates: number;
  minSeverity: number;
  costPerUnit: number;
  schedule: string;
  alertsEnabled: boolean;
  alertChannels: string[];
  alertSeverityThreshold: "low" | "medium" | "high";
  autoApproveEnabled: boolean;
  autoApproveMaxValue: number;
  enabledSignals: string[];
  customThresholds: Record<string, number>;
  notes: string;
}

export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  confidenceFloor: 0.5,
  maxCandidates: 6,
  minSeverity: 0.1,
  costPerUnit: 0,
  schedule: "0 */2 * * *",
  alertsEnabled: true,
  alertChannels: ["dashboard"],
  alertSeverityThreshold: "medium",
  autoApproveEnabled: false,
  autoApproveMaxValue: 500,
  enabledSignals: [],
  customThresholds: {},
  notes: "",
};

export interface AgentNodeData extends Record<string, unknown> {
  label: string;
  agent: string;
  domain: AgentDomain;
  meter: string;
  status: AgentStatus;
  signals: string[];
  lastRun: string;
  findings: number;
  monthlyValue: number;
  description: string;
  config: AgentConfig;
  isCustom?: boolean;
}

export interface TriggerNodeData extends Record<string, unknown> {
  label: string;
  schedule: string;
  type: "cron" | "webhook" | "manual";
}

export interface OutputNodeData extends Record<string, unknown> {
  label: string;
  destination: string;
  type: "dashboard" | "slack" | "webhook" | "email";
}

const DOMAIN_COLORS: Record<AgentDomain, string> = {
  scheduling: "hsl(220 70% 55%)",
  storage: "hsl(160 60% 45%)",
  network: "hsl(280 60% 55%)",
  commitments: "hsl(35 90% 50%)",
  power: "hsl(0 70% 55%)",
  training: "hsl(190 70% 45%)",
  inference: "hsl(320 60% 50%)",
  coordination: "hsl(45 90% 50%)",
  custom: "hsl(260 50% 55%)",
};

export { DOMAIN_COLORS };

export const ALL_SIGNALS: Record<AgentDomain, string[]> = {
  scheduling: ["idle_allocation", "over_allocation", "queue_inefficiency", "fragmentation", "poor_placement"],
  storage: ["orphaned_volume", "cold_checkpoint", "snapshot_sprawl", "duplicate_dataset"],
  network: ["cross_az_traffic", "data_locality", "image_pull_churn"],
  commitments: ["reservation_underuse", "spot_eligible", "commitment_expiry"],
  power: ["capped_clocks", "pue_placement", "off_peak_shift"],
  training: ["dataloader_stall", "restart_waste", "nonconverging_sweep", "checkpoint_overhead"],
  inference: ["idle_endpoint", "over_provisioned_replicas", "batch_headroom"],
  coordination: [],
  custom: [],
};

export const METERS: Record<AgentDomain, string> = {
  scheduling: "GPU-h",
  storage: "GB-month",
  network: "GB",
  commitments: "$ committed",
  power: "kWh",
  training: "GPU-h",
  inference: "replica-h",
  coordination: "all",
  custom: "custom",
};

export const DOMAIN_THRESHOLDS: Record<string, { label: string; default: number; min: number; max: number; step: number }[]> = {
  scheduling: [
    { label: "Min idle %", default: 20, min: 5, max: 80, step: 5 },
    { label: "Min duration (min)", default: 30, min: 5, max: 240, step: 5 },
  ],
  storage: [
    { label: "Orphan age (days)", default: 30, min: 1, max: 365, step: 1 },
    { label: "Cold checkpoint age (days)", default: 14, min: 1, max: 180, step: 1 },
    { label: "Max snapshots per volume", default: 3, min: 1, max: 50, step: 1 },
  ],
  network: [
    { label: "Min billable GB", default: 1, min: 0.1, max: 100, step: 0.1 },
    { label: "Min pull count for churn", default: 2, min: 2, max: 20, step: 1 },
  ],
  commitments: [
    { label: "Underuse threshold %", default: 30, min: 5, max: 90, step: 5 },
    { label: "Expiry horizon (days)", default: 30, min: 7, max: 180, step: 1 },
    { label: "Spot discount factor", default: 0.3, min: 0.1, max: 0.9, step: 0.05 },
  ],
  power: [
    { label: "Min throttle %", default: 5, min: 1, max: 50, step: 1 },
    { label: "Min PUE delta", default: 0.05, min: 0.01, max: 0.5, step: 0.01 },
    { label: "Max deferrable hours", default: 8, min: 1, max: 24, step: 1 },
  ],
  training: [
    { label: "Stall threshold %", default: 5, min: 1, max: 30, step: 1 },
    { label: "Checkpoint threshold %", default: 10, min: 1, max: 50, step: 1 },
    { label: "Sweep failure ratio %", default: 50, min: 20, max: 90, step: 5 },
  ],
  inference: [
    { label: "Idle RPS threshold", default: 0.01, min: 0, max: 1, step: 0.01 },
    { label: "Low utilization %", default: 30, min: 5, max: 80, step: 5 },
    { label: "Batch fill threshold %", default: 30, min: 5, max: 80, step: 5 },
  ],
};

export interface CatalogEntry {
  id: string;
  label: string;
  domain: AgentDomain;
  meter: string;
  signals: string[];
  description: string;
  builtin: boolean;
}

export const AGENT_CATALOG: CatalogEntry[] = [
  { id: "idle_allocation_agent", label: "Idle Allocation", domain: "scheduling", meter: "GPU-h", signals: ["idle_allocation"], description: "Detects GPUs held by jobs but not doing useful work.", builtin: true },
  { id: "over_allocation_agent", label: "Over-allocation", domain: "scheduling", meter: "GPU-h", signals: ["over_allocation"], description: "Jobs holding more GPUs than their workload needs.", builtin: true },
  { id: "queue_efficiency_agent", label: "Queue Efficiency", domain: "scheduling", meter: "GPU-h", signals: ["queue_inefficiency"], description: "Queue wait that could have been avoided with better scheduling.", builtin: true },
  { id: "fragmentation_placement_agent", label: "Fragmentation", domain: "scheduling", meter: "GPU-h", signals: ["fragmentation", "poor_placement"], description: "GPU fragmentation preventing larger jobs from scheduling.", builtin: true },
  { id: "storage_efficiency_agent", label: "Storage Efficiency", domain: "storage", meter: "GB-month", signals: ["orphaned_volume", "cold_checkpoint", "snapshot_sprawl", "duplicate_dataset"], description: "Orphaned volumes, cold checkpoints, snapshot sprawl, duplicate datasets.", builtin: true },
  { id: "network_efficiency_agent", label: "Network Efficiency", domain: "network", meter: "GB", signals: ["cross_az_traffic", "data_locality", "image_pull_churn"], description: "Cross-AZ traffic, data locality waste, container image pull churn.", builtin: true },
  { id: "commitment_coverage_agent", label: "Commitment Coverage", domain: "commitments", meter: "$ committed", signals: ["reservation_underuse", "spot_eligible", "commitment_expiry"], description: "Reserved instance underuse, spot-eligible workloads, expiring commitments.", builtin: true },
  { id: "power_efficiency_agent", label: "Power & Thermal", domain: "power", meter: "kWh", signals: ["capped_clocks", "pue_placement", "off_peak_shift"], description: "Clock-capped GPUs, PUE-aware placement, off-peak tariff shifting.", builtin: true },
  { id: "training_efficiency_agent", label: "Training Efficiency", domain: "training", meter: "GPU-h", signals: ["dataloader_stall", "restart_waste", "nonconverging_sweep", "checkpoint_overhead"], description: "Dataloader stalls, restart waste, non-converging sweeps, checkpoint overhead.", builtin: true },
  { id: "inference_efficiency_agent", label: "Inference Efficiency", domain: "inference", meter: "replica-h", signals: ["idle_endpoint", "over_provisioned_replicas", "batch_headroom"], description: "Idle endpoints, over-provisioned replicas, batch-size headroom.", builtin: true },
];

function makeConfig(signals: string[], domain: AgentDomain): AgentConfig {
  const thresholds: Record<string, number> = {};
  for (const t of DOMAIN_THRESHOLDS[domain] ?? []) {
    thresholds[t.label] = t.default;
  }
  return { ...DEFAULT_AGENT_CONFIG, enabledSignals: [...signals], customThresholds: thresholds };
}

export const initialNodes: Node[] = [
  {
    id: "trigger-cron",
    type: "trigger",
    position: { x: 50, y: 320 },
    data: { label: "Scheduled Run", schedule: "Every 2 hours", type: "cron" } satisfies TriggerNodeData,
  },
  {
    id: "coordinator",
    type: "coordinator",
    position: { x: 300, y: 280 },
    data: {
      label: "Agent Coordinator", agent: "coordinator", domain: "coordination", meter: "all",
      status: "active", signals: [], lastRun: "never", findings: 0, monthlyValue: 0,
      description: "Runs all agents, deduplicates findings across meters, resolves conflicts, and produces a single ranked list.",
      config: { ...DEFAULT_AGENT_CONFIG },
    } satisfies AgentNodeData,
  },
  ...AGENT_CATALOG.map((entry, i) => ({
    id: entry.id.replace(/_agent$/, "").replace(/_/g, "-"),
    type: "agent" as const,
    position: { x: 620, y: i * 120 },
    data: {
      label: entry.label, agent: entry.id, domain: entry.domain, meter: entry.meter,
      status: "active" as AgentStatus, signals: entry.signals, lastRun: "never",
      findings: 0,
      monthlyValue: 0,
      description: entry.description,
      config: makeConfig(entry.signals, entry.domain),
    } satisfies AgentNodeData,
  })),
  {
    id: "output-dashboard",
    type: "output",
    position: { x: 960, y: 320 },
    data: { label: "Dashboard", destination: "Findings view", type: "dashboard" } satisfies OutputNodeData,
  },
  {
    id: "output-slack",
    type: "output",
    position: { x: 960, y: 460 },
    data: { label: "Slack Alert", destination: "#gpu-fleet-alerts", type: "slack" } satisfies OutputNodeData,
  },
];

const agentNodeIds = AGENT_CATALOG.map((e) => e.id.replace(/_agent$/, "").replace(/_/g, "-"));

export const initialEdges: Edge[] = [
  { id: "e-trigger-coord", source: "trigger-cron", target: "coordinator", animated: true, style: { stroke: DOMAIN_COLORS.coordination, strokeWidth: 2 } },
  ...agentNodeIds.map((id) => ({
    id: `e-coord-${id}`,
    source: "coordinator",
    target: id,
    animated: true,
    style: { stroke: "hsl(var(--muted-foreground) / 0.3)", strokeWidth: 1.5 },
  })),
  { id: "e-coord-dash", source: "coordinator", target: "output-dashboard", animated: true, style: { stroke: DOMAIN_COLORS.coordination, strokeWidth: 2 } },
  { id: "e-coord-slack", source: "coordinator", target: "output-slack", animated: true, style: { stroke: DOMAIN_COLORS.coordination, strokeWidth: 1.5 } },
];
