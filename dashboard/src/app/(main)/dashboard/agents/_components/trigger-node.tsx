"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { Clock, Webhook, MousePointerClick } from "lucide-react";
import type { TriggerNodeData } from "./agent-data";

type TriggerNode = Node<TriggerNodeData, "trigger">;

const TRIGGER_ICONS = {
  cron: Clock,
  webhook: Webhook,
  manual: MousePointerClick,
} as const;

export function TriggerNode({ data, selected }: NodeProps<TriggerNode>) {
  const Icon = TRIGGER_ICONS[data.type];

  return (
    <div
      className={`group relative w-[180px] rounded-xl border border-dashed bg-card text-card-foreground shadow-sm transition-all hover:shadow-md ${
        selected ? "ring-2 ring-primary" : ""
      }`}
      style={{ borderColor: "hsl(142 50% 50% / 0.5)" }}
    >
      <div className="flex items-center gap-2.5 px-3 py-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-emerald-500/10">
          <Icon className="size-4 text-emerald-500" />
        </div>
        <div>
          <p className="text-xs font-semibold">{data.label}</p>
          <p className="text-[10px] text-muted-foreground">{data.schedule}</p>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !border-2 !border-background !bg-emerald-500" />
    </div>
  );
}
