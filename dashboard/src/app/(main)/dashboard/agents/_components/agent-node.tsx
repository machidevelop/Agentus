"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import {
  Cpu,
  HardDrive,
  Network,
  DollarSign,
  Zap,
  GraduationCap,
  Server,
  Layers,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentNodeData, AgentDomain } from "./agent-data";
import { DOMAIN_COLORS } from "./agent-data";

const DOMAIN_ICONS: Record<AgentDomain, React.ElementType> = {
  scheduling: Cpu,
  storage: HardDrive,
  network: Network,
  commitments: DollarSign,
  power: Zap,
  training: GraduationCap,
  inference: Server,
  coordination: Layers,
  custom: Layers,
};

type AgentNode = Node<AgentNodeData, "agent">;

export function AgentNode({ data, selected }: NodeProps<AgentNode>) {
  const Icon = DOMAIN_ICONS[data.domain];
  const color = DOMAIN_COLORS[data.domain];

  return (
    <div
      className={`group relative w-[220px] rounded-xl border bg-card text-card-foreground shadow-md transition-all hover:shadow-lg ${
        selected ? "ring-2 ring-primary" : ""
      }`}
      style={{ borderColor: `${color}40` }}
    >
      <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !border-2 !border-background" style={{ background: color }} />

      {/* Header */}
      <div
        className="flex items-center gap-2 rounded-t-xl px-3 py-2"
        style={{ background: `${color}15` }}
      >
        <div
          className="flex size-7 items-center justify-center rounded-lg"
          style={{ background: `${color}25` }}
        >
          <Icon className="size-4" style={{ color }} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold truncate">{data.label}</p>
          <p className="text-[10px] text-muted-foreground">{data.meter}</p>
        </div>
        <div className="relative flex size-2 items-center justify-center">
          <span
            className={`absolute inline-flex size-full rounded-full opacity-75 ${
              data.status === "active" ? "animate-ping" : ""
            }`}
            style={{
              background:
                data.status === "active"
                  ? "hsl(142 72% 50%)"
                  : data.status === "paused"
                    ? "hsl(45 93% 50%)"
                    : "hsl(0 72% 50%)",
            }}
          />
          <span
            className="relative inline-flex size-2 rounded-full"
            style={{
              background:
                data.status === "active"
                  ? "hsl(142 72% 50%)"
                  : data.status === "paused"
                    ? "hsl(45 93% 50%)"
                    : "hsl(0 72% 50%)",
            }}
          />
        </div>
      </div>

      {/* Body */}
      <div className="px-3 py-2 space-y-1.5">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-muted-foreground">{data.findings} findings</span>
          <span className="font-medium" style={{ color }}>
            ${data.monthlyValue.toLocaleString()}/mo
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {data.signals.slice(0, 3).map((s) => (
            <Badge key={s} variant="outline" className="!text-[9px] !h-4 !px-1.5">
              {s.replace(/_/g, " ")}
            </Badge>
          ))}
          {data.signals.length > 3 && (
            <Badge variant="outline" className="!text-[9px] !h-4 !px-1.5">
              +{data.signals.length - 3}
            </Badge>
          )}
        </div>
        <p className="text-[10px] text-muted-foreground">{data.lastRun}</p>
      </div>

      <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !border-2 !border-background" style={{ background: color }} />
    </div>
  );
}
