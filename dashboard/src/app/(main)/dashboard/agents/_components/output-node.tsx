"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { LayoutDashboard, MessageSquare, Webhook, Mail } from "lucide-react";
import type { OutputNodeData } from "./agent-data";

type OutputNode = Node<OutputNodeData, "output">;

const OUTPUT_ICONS = {
  dashboard: LayoutDashboard,
  slack: MessageSquare,
  webhook: Webhook,
  email: Mail,
} as const;

export function OutputNode({ data, selected }: NodeProps<OutputNode>) {
  const Icon = OUTPUT_ICONS[data.type];

  return (
    <div
      className={`group relative w-[180px] rounded-xl border border-dashed bg-card text-card-foreground shadow-sm transition-all hover:shadow-md ${
        selected ? "ring-2 ring-primary" : ""
      }`}
      style={{ borderColor: "hsl(280 50% 55% / 0.5)" }}
    >
      <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !border-2 !border-background !bg-purple-500" />
      <div className="flex items-center gap-2.5 px-3 py-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-purple-500/10">
          <Icon className="size-4 text-purple-500" />
        </div>
        <div>
          <p className="text-xs font-semibold">{data.label}</p>
          <p className="text-[10px] text-muted-foreground">{data.destination}</p>
        </div>
      </div>
    </div>
  );
}
