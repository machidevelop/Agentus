"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { Layers } from "lucide-react";
import type { AgentNodeData } from "./agent-data";
import { DOMAIN_COLORS } from "./agent-data";

type CoordinatorNode = Node<AgentNodeData, "coordinator">;

export function CoordinatorNode({ data, selected }: NodeProps<CoordinatorNode>) {
  const color = DOMAIN_COLORS.coordination;

  return (
    <div
      className={`group relative w-[240px] rounded-2xl border-2 bg-card text-card-foreground shadow-lg transition-all hover:shadow-xl ${
        selected ? "ring-2 ring-primary" : ""
      }`}
      style={{ borderColor: `${color}60` }}
    >
      <Handle type="target" position={Position.Left} className="!w-3 !h-3 !border-2 !border-background" style={{ background: color }} />

      {/* Header */}
      <div
        className="flex items-center gap-3 rounded-t-xl px-4 py-3"
        style={{ background: `${color}12` }}
      >
        <div
          className="flex size-9 items-center justify-center rounded-xl"
          style={{ background: `${color}25`, boxShadow: `0 0 12px ${color}30` }}
        >
          <Layers className="size-5" style={{ color }} />
        </div>
        <div>
          <p className="text-sm font-bold">{data.label}</p>
          <p className="text-[11px] text-muted-foreground">Multi-meter dedup & ranking</p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 px-4 py-3">
        <div>
          <p className="text-[10px] text-muted-foreground">Total findings</p>
          <p className="text-lg font-bold">{data.findings}</p>
        </div>
        <div>
          <p className="text-[10px] text-muted-foreground">Monthly value</p>
          <p className="text-lg font-bold" style={{ color }}>
            ${(data.monthlyValue / 1000).toFixed(0)}k
          </p>
        </div>
        <div className="col-span-2">
          <p className="text-[10px] text-muted-foreground">{data.lastRun}</p>
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="!w-3 !h-3 !border-2 !border-background" style={{ background: color }} />
    </div>
  );
}
