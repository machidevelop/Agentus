"use client";

import { useState } from "react";
import {
  Cpu, HardDrive, Network, DollarSign, Zap, GraduationCap, Server, Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import {
  AGENT_CATALOG, DOMAIN_COLORS, type AgentDomain, type CatalogEntry,
} from "./agent-data";

const DOMAIN_ICONS: Record<AgentDomain, React.ElementType> = {
  scheduling: Cpu, storage: HardDrive, network: Network, commitments: DollarSign,
  power: Zap, training: GraduationCap, inference: Server, coordination: Sparkles,
  custom: Sparkles,
};

const DOMAIN_ORDER: AgentDomain[] = [
  "scheduling", "storage", "network", "commitments", "power", "training", "inference",
];

interface AgentCatalogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAddAgent: (entry: CatalogEntry) => void;
  onCreateCustom: () => void;
  existingAgentIds: Set<string>;
}

export function AgentCatalog({
  open, onOpenChange, onAddAgent, onCreateCustom, existingAgentIds,
}: AgentCatalogProps) {
  const [search, setSearch] = useState("");
  const filtered = AGENT_CATALOG.filter(
    (e) =>
      e.label.toLowerCase().includes(search.toLowerCase()) ||
      e.domain.toLowerCase().includes(search.toLowerCase()) ||
      e.signals.some((s) => s.includes(search.toLowerCase())),
  );

  const grouped = DOMAIN_ORDER.reduce<Record<string, CatalogEntry[]>>((acc, domain) => {
    const items = filtered.filter((e) => e.domain === domain);
    if (items.length > 0) acc[domain] = items;
    return acc;
  }, {});

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="w-[380px] p-0 flex flex-col">
        <SheetHeader className="px-4 pt-4 pb-0">
          <SheetTitle className="text-base">Agent Catalog</SheetTitle>
          <SheetDescription className="text-xs">
            Add a built-in agent or create your own custom agent.
          </SheetDescription>
        </SheetHeader>

        <div className="px-4 py-3">
          <Input
            placeholder="Search agents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 text-xs"
          />
        </div>

        <ScrollArea className="flex-1 px-4">
          <div className="space-y-4 pb-4">
            {/* Custom agent card */}
            <button
              type="button"
              onClick={onCreateCustom}
              className="w-full rounded-xl border-2 border-dashed p-3 text-left transition-all hover:border-primary/40 hover:bg-muted/50"
              style={{ borderColor: `${DOMAIN_COLORS.custom}30` }}
            >
              <div className="flex items-center gap-2.5">
                <div
                  className="flex size-8 items-center justify-center rounded-lg"
                  style={{ background: `${DOMAIN_COLORS.custom}15` }}
                >
                  <Sparkles className="size-4" style={{ color: DOMAIN_COLORS.custom }} />
                </div>
                <div>
                  <p className="text-xs font-semibold">Create Custom Agent</p>
                  <p className="text-[10px] text-muted-foreground">
                    Define your own domain, meter, signals, and thresholds
                  </p>
                </div>
              </div>
            </button>

            <Separator />

            {/* Built-in agents by domain */}
            {Object.entries(grouped).map(([domain, entries]) => {
              const Icon = DOMAIN_ICONS[domain as AgentDomain];
              const color = DOMAIN_COLORS[domain as AgentDomain];
              return (
                <div key={domain} className="space-y-2">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    <Icon className="size-3.5" style={{ color }} />
                    {domain}
                  </div>
                  {entries.map((entry) => {
                    const alreadyAdded = existingAgentIds.has(entry.id);
                    return (
                      <div
                        key={entry.id}
                        className={`rounded-lg border p-3 transition-all ${
                          alreadyAdded ? "opacity-50" : "hover:border-primary/30 hover:shadow-sm"
                        }`}
                        style={{ borderColor: `${color}20` }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <p className="text-xs font-semibold truncate">{entry.label}</p>
                              <Badge variant="outline" className="!text-[9px] !h-4 !px-1.5 shrink-0">
                                {entry.meter}
                              </Badge>
                            </div>
                            <p className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">
                              {entry.description}
                            </p>
                            <div className="flex flex-wrap gap-1 mt-1.5">
                              {entry.signals.slice(0, 3).map((s) => (
                                <Badge key={s} variant="secondary" className="!text-[8px] !h-3.5 !px-1">
                                  {s.replace(/_/g, " ")}
                                </Badge>
                              ))}
                              {entry.signals.length > 3 && (
                                <Badge variant="secondary" className="!text-[8px] !h-3.5 !px-1">
                                  +{entry.signals.length - 3}
                                </Badge>
                              )}
                            </div>
                          </div>
                          <Button
                            size="sm"
                            variant={alreadyAdded ? "outline" : "default"}
                            className="h-7 text-[10px] px-2.5 shrink-0"
                            disabled={alreadyAdded}
                            onClick={() => onAddAgent(entry)}
                          >
                            {alreadyAdded ? "Added" : "Add"}
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
