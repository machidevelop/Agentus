import { AgentCanvas } from "./_components/agent-canvas";

export default function Page() {
  return (
    <div data-content-padding="false" className="flex flex-col h-[calc(100vh-3rem)]">
      <div className="flex items-center justify-between px-6 py-3 border-b bg-background">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Agent Workflows</h1>
          <p className="text-xs text-muted-foreground">
            Drag, connect, and configure agents — n8n style
          </p>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <AgentCanvas />
      </div>
    </div>
  );
}
