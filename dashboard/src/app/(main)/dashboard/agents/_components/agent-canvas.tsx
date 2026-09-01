"use client";

import { useCallback, useMemo, useState, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  addEdge,
  BackgroundVariant,
  type Connection,
  type NodeTypes,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { Button } from "@/components/ui/button";
import {
  PlusCircle,
  ZapIcon,
  PlayIcon,
  LayoutGrid,
} from "lucide-react";

import { AgentNode } from "./agent-node";
import { CoordinatorNode } from "./coordinator-node";
import { TriggerNode } from "./trigger-node";
import { OutputNode } from "./output-node";
import { NodeDetailPanel } from "./node-detail-panel";
import { AgentCatalog } from "./agent-catalog";
import { CustomAgentDialog } from "./custom-agent-dialog";
import {
  initialNodes,
  initialEdges,
  DOMAIN_COLORS,
  DEFAULT_AGENT_CONFIG,
  DOMAIN_THRESHOLDS,
  ALL_SIGNALS,
  type AgentDomain,
  type AgentNodeData,
  type TriggerNodeData,
  type OutputNodeData,
  type CatalogEntry,
  type AgentConfig,
} from "./agent-data";

const nodeTypes: NodeTypes = {
  agent: AgentNode,
  coordinator: CoordinatorNode,
  trigger: TriggerNode,
  output: OutputNode,
};

const MINIMAP_COLORS: Record<string, string> = {
  agent: "hsl(220 70% 55%)",
  coordinator: DOMAIN_COLORS.coordination,
  trigger: "hsl(142 50% 50%)",
  output: "hsl(280 50% 55%)",
};

let nodeIdCounter = 100;
function nextId(prefix: string) {
  nodeIdCounter += 1;
  return `${prefix}-${nodeIdCounter}`;
}

function makeConfigForEntry(entry: CatalogEntry): AgentConfig {
  const thresholds: Record<string, number> = {};
  for (const t of DOMAIN_THRESHOLDS[entry.domain] ?? []) {
    thresholds[t.label] = t.default;
  }
  const signals = entry.builtin
    ? ALL_SIGNALS[entry.domain] ?? entry.signals
    : entry.signals;
  return { ...DEFAULT_AGENT_CONFIG, enabledSignals: [...signals], customThresholds: thresholds };
}

export function AgentCanvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [customDialogOpen, setCustomDialogOpen] = useState(false);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const existingAgentIds = useMemo(
    () => new Set(nodes.filter((n) => n.type === "agent").map((n) => (n.data as AgentNodeData).agent)),
    [nodes],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            animated: true,
            style: { strokeWidth: 1.5, stroke: "hsl(var(--muted-foreground) / 0.3)" },
          },
          eds,
        ),
      );
    },
    [setEdges],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => setSelectedNode(node),
    [],
  );

  const onPaneClick = useCallback(() => setSelectedNode(null), []);

  const onAddAgent = useCallback(
    (entry: CatalogEntry) => {
      const id = nextId("agent");
      const agentCount = nodes.filter((n) => n.type === "agent").length;
      const color = DOMAIN_COLORS[entry.domain] ?? DOMAIN_COLORS.custom;

      const newNode: Node = {
        id,
        type: "agent",
        position: { x: 620, y: agentCount * 120 },
        data: {
          label: entry.label,
          agent: entry.id,
          domain: entry.domain,
          meter: entry.meter,
          status: "active",
          signals: entry.signals,
          lastRun: "never",
          findings: 0,
          monthlyValue: 0,
          description: entry.description,
          config: makeConfigForEntry(entry),
          isCustom: !entry.builtin,
        } satisfies AgentNodeData,
      };

      const newEdge: Edge = {
        id: `e-coord-${id}`,
        source: "coordinator",
        target: id,
        animated: true,
        style: { stroke: `${color}60`, strokeWidth: 1.5 },
      };

      setNodes((nds) => [...nds, newNode]);
      setEdges((eds) => [...eds, newEdge]);
      setCatalogOpen(false);
    },
    [nodes, setNodes, setEdges],
  );

  const onCreateCustomAgent = useCallback(
    (entry: CatalogEntry) => {
      onAddAgent(entry);
      setCustomDialogOpen(false);
    },
    [onAddAgent],
  );

  const onUpdateNodeData = useCallback(
    (nodeId: string, partial: Partial<AgentNodeData | TriggerNodeData | OutputNodeData>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...partial } } : n,
        ),
      );
      setSelectedNode((prev) =>
        prev && prev.id === nodeId
          ? { ...prev, data: { ...prev.data, ...partial } }
          : prev,
      );
    },
    [setNodes],
  );

  const onDeleteNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedNode(null);
    },
    [setNodes, setEdges],
  );

  const onDuplicateNode = useCallback(
    (node: Node) => {
      const id = nextId(node.type ?? "agent");
      const duplicate: Node = {
        ...node,
        id,
        position: { x: node.position.x + 40, y: node.position.y + 40 },
        selected: false,
        data: { ...node.data, label: `${(node.data as { label: string }).label} (copy)` },
      };

      const incomingEdges = edges
        .filter((e) => e.target === node.id)
        .map((e) => ({
          ...e,
          id: `e-${e.source}-${id}`,
          target: id,
        }));

      setNodes((nds) => [...nds, duplicate]);
      setEdges((eds) => [...eds, ...incomingEdges]);
    },
    [edges, setNodes, setEdges],
  );

  const onAddTrigger = useCallback(() => {
    const id = nextId("trigger");
    const triggerCount = nodes.filter((n) => n.type === "trigger").length;
    const newNode: Node = {
      id,
      type: "trigger",
      position: { x: 50, y: 200 + triggerCount * 140 },
      data: {
        label: "New Trigger",
        schedule: "Every hour",
        type: "cron",
      } satisfies TriggerNodeData,
    };
    const newEdge: Edge = {
      id: `e-${id}-coordinator`,
      source: id,
      target: "coordinator",
      animated: true,
      style: { stroke: DOMAIN_COLORS.coordination, strokeWidth: 2 },
    };
    setNodes((nds) => [...nds, newNode]);
    setEdges((eds) => [...eds, newEdge]);
  }, [nodes, setNodes, setEdges]);

  const proOptions = useMemo(() => ({ hideAttribution: true }), []);

  const agentNodes = nodes.filter((n) => n.type === "agent");
  const activeCount = agentNodes.filter(
    (n) => (n.data as AgentNodeData).status === "active",
  ).length;

  return (
    <div className="flex h-full">
      <div ref={reactFlowWrapper} className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          nodeTypes={nodeTypes}
          proOptions={proOptions}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.2}
          maxZoom={2}
          snapToGrid
          snapGrid={[20, 20]}
          deleteKeyCode={["Backspace", "Delete"]}
          className="!bg-background"
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            className="!bg-background"
            color="hsl(var(--muted-foreground) / 0.15)"
          />
          <Controls
            showInteractive={false}
            className="!bg-card !border !border-border !rounded-lg !shadow-sm [&>button]:!bg-card [&>button]:!border-border [&>button]:!text-foreground [&>button:hover]:!bg-muted"
          />
          <MiniMap
            nodeColor={(node) => MINIMAP_COLORS[node.type ?? "agent"] ?? "hsl(var(--muted-foreground))"}
            maskColor="hsl(var(--background) / 0.85)"
            className="!bg-card !border !border-border !rounded-lg !shadow-sm"
            pannable
            zoomable
          />

          <Panel position="top-left" className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 bg-card shadow-sm"
              onClick={() => setCatalogOpen(true)}
            >
              <PlusCircle className="size-3.5" />
              Add agent
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 bg-card shadow-sm"
              onClick={onAddTrigger}
            >
              <ZapIcon className="size-3.5" />
              Add trigger
            </Button>
          </Panel>

          <Panel position="top-right" className="flex items-center gap-2">
            <Button size="sm" variant="default" className="gap-1.5 shadow-sm">
              <PlayIcon className="size-3.5" />
              Run all
            </Button>
          </Panel>

          <Panel
            position="bottom-left"
            className="flex items-center gap-3 text-[11px] text-muted-foreground bg-card/80 backdrop-blur-sm px-3 py-1.5 rounded-lg border shadow-sm"
          >
            <span>{agentNodes.length} agents</span>
            <span className="text-border">|</span>
            <span>{edges.length} connections</span>
            <span className="text-border">|</span>
            <span>{activeCount} active</span>
          </Panel>
        </ReactFlow>
      </div>

      {/* Detail side panel */}
      {selectedNode && (
        <div className="w-[320px] border-l bg-card overflow-hidden flex flex-col">
          <NodeDetailPanel
            nodeType={selectedNode.type ?? "agent"}
            data={selectedNode.data as AgentNodeData | TriggerNodeData | OutputNodeData}
            onClose={() => setSelectedNode(null)}
            onUpdate={(partial) => onUpdateNodeData(selectedNode.id, partial)}
            onDelete={() => onDeleteNode(selectedNode.id)}
            onDuplicate={() => onDuplicateNode(selectedNode)}
          />
        </div>
      )}

      {/* Catalog sheet */}
      <AgentCatalog
        open={catalogOpen}
        onOpenChange={setCatalogOpen}
        onAddAgent={onAddAgent}
        onCreateCustom={() => {
          setCatalogOpen(false);
          setCustomDialogOpen(true);
        }}
        existingAgentIds={existingAgentIds}
      />

      {/* Custom agent dialog */}
      <CustomAgentDialog
        open={customDialogOpen}
        onOpenChange={setCustomDialogOpen}
        onCreateAgent={onCreateCustomAgent}
      />
    </div>
  );
}
