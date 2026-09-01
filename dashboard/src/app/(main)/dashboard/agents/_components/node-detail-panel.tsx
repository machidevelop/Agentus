"use client";

import { useState } from "react";
import {
  X, PlayIcon, PauseIcon, Trash2, Copy, RotateCcw,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import type {
  AgentNodeData, TriggerNodeData, OutputNodeData, AgentConfig,
} from "./agent-data";
import {
  DOMAIN_COLORS, DOMAIN_THRESHOLDS, ALL_SIGNALS, DEFAULT_AGENT_CONFIG,
  type AgentDomain,
} from "./agent-data";

interface NodeDetailPanelProps {
  nodeType: string;
  data: AgentNodeData | TriggerNodeData | OutputNodeData;
  onClose: () => void;
  onUpdate: (data: Partial<AgentNodeData | TriggerNodeData | OutputNodeData>) => void;
  onDelete: () => void;
  onDuplicate: () => void;
}

export function NodeDetailPanel({
  nodeType, data, onClose, onUpdate, onDelete, onDuplicate,
}: NodeDetailPanelProps) {
  if (nodeType === "agent" || nodeType === "coordinator") {
    return (
      <AgentDetail
        data={data as AgentNodeData}
        isCoordinator={nodeType === "coordinator"}
        onClose={onClose}
        onUpdate={onUpdate as (d: Partial<AgentNodeData>) => void}
        onDelete={onDelete}
        onDuplicate={onDuplicate}
      />
    );
  }
  if (nodeType === "trigger") {
    return (
      <TriggerDetail
        data={data as TriggerNodeData}
        onClose={onClose}
        onUpdate={onUpdate as (d: Partial<TriggerNodeData>) => void}
        onDelete={onDelete}
      />
    );
  }
  return (
    <OutputDetail
      data={data as OutputNodeData}
      onClose={onClose}
      onUpdate={onUpdate as (d: Partial<OutputNodeData>) => void}
      onDelete={onDelete}
    />
  );
}

function AgentDetail({
  data, isCoordinator, onClose, onUpdate, onDelete, onDuplicate,
}: {
  data: AgentNodeData;
  isCoordinator: boolean;
  onClose: () => void;
  onUpdate: (d: Partial<AgentNodeData>) => void;
  onDelete: () => void;
  onDuplicate: () => void;
}) {
  const color = DOMAIN_COLORS[data.domain];
  const config = data.config ?? DEFAULT_AGENT_CONFIG;
  const domainSignals = ALL_SIGNALS[data.domain] ?? [];

  const updateConfig = (partial: Partial<AgentConfig>) => {
    onUpdate({ config: { ...config, ...partial } });
  };

  const updateThreshold = (key: string, value: number) => {
    updateConfig({ customThresholds: { ...config.customThresholds, [key]: value } });
  };

  const toggleSignal = (signal: string) => {
    const current = config.enabledSignals;
    const next = current.includes(signal)
      ? current.filter((s) => s !== signal)
      : [...current, signal];
    updateConfig({ enabledSignals: next });
  };

  const thresholdDefs = DOMAIN_THRESHOLDS[data.domain] ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2 min-w-0">
          <div className="size-3 rounded-full shrink-0" style={{ background: color }} />
          <h3 className="text-sm font-semibold truncate">{data.label}</h3>
          {data.isCustom && (
            <Badge variant="outline" className="!text-[8px] !h-3.5 !px-1 shrink-0">custom</Badge>
          )}
        </div>
        <Button variant="ghost" size="icon" className="size-7 shrink-0" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="general" className="flex-1 flex flex-col min-h-0">
        <TabsList className="mx-4 mt-2 h-8 w-auto">
          <TabsTrigger value="general" className="text-[10px] h-6 px-2">General</TabsTrigger>
          <TabsTrigger value="signals" className="text-[10px] h-6 px-2">Signals</TabsTrigger>
          <TabsTrigger value="thresholds" className="text-[10px] h-6 px-2">Tuning</TabsTrigger>
          <TabsTrigger value="alerts" className="text-[10px] h-6 px-2">Alerts</TabsTrigger>
        </TabsList>

        <ScrollArea className="flex-1">
          {/* General tab */}
          <TabsContent value="general" className="px-4 pb-4 space-y-4 mt-0">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Name</Label>
              <Input
                value={data.label}
                onChange={(e) => onUpdate({ label: e.target.value })}
                className="h-8 text-xs"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Description</Label>
              <Textarea
                value={data.description}
                onChange={(e) => onUpdate({ description: e.target.value })}
                className="text-xs min-h-[50px] resize-none"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Domain</Label>
                <Select
                  value={data.domain}
                  onValueChange={(v) => onUpdate({ domain: v as AgentDomain })}
                  disabled={!data.isCustom}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.keys(DOMAIN_COLORS).filter((d) => d !== "coordination").map((d) => (
                      <SelectItem key={d} value={d} className="text-xs">{d}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Meter</Label>
                <Input
                  value={data.meter}
                  onChange={(e) => onUpdate({ meter: e.target.value })}
                  className="h-8 text-xs"
                  disabled={!data.isCustom}
                />
              </div>
            </div>

            <Separator />

            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Performance
              </h4>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border p-2.5">
                  <p className="text-[10px] text-muted-foreground">Findings</p>
                  <p className="text-xl font-bold">{data.findings}</p>
                </div>
                <div className="rounded-lg border p-2.5">
                  <p className="text-[10px] text-muted-foreground">Monthly value</p>
                  <p className="text-xl font-bold" style={{ color }}>
                    ${data.monthlyValue.toLocaleString()}
                  </p>
                </div>
              </div>
              <div className="rounded-lg border p-2.5">
                <p className="text-[10px] text-muted-foreground">Last run</p>
                <p className="text-sm font-medium">{data.lastRun}</p>
              </div>
            </div>

            <Separator />

            <div className="space-y-3">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Schedule
              </h4>
              <div className="space-y-1.5">
                <Label className="text-xs">Cron Expression</Label>
                <Input
                  value={config.schedule}
                  onChange={(e) => updateConfig({ schedule: e.target.value })}
                  className="h-8 text-xs font-mono"
                  placeholder="0 */2 * * *"
                />
                <p className="text-[10px] text-muted-foreground">
                  Default: every 2 hours. Use standard cron syntax.
                </p>
              </div>
            </div>

            <Separator />

            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Notes</Label>
              <Textarea
                value={config.notes}
                onChange={(e) => updateConfig({ notes: e.target.value })}
                className="text-xs min-h-[40px] resize-none"
                placeholder="Internal notes about this agent configuration..."
              />
            </div>
          </TabsContent>

          {/* Signals tab */}
          <TabsContent value="signals" className="px-4 pb-4 space-y-4 mt-0">
            <p className="text-[10px] text-muted-foreground">
              Toggle which signal types this agent watches. Disabled signals are skipped during analysis.
            </p>
            {domainSignals.length > 0 ? (
              <div className="space-y-2">
                {domainSignals.map((signal) => {
                  const enabled = config.enabledSignals.includes(signal);
                  return (
                    <label
                      key={signal}
                      className="flex items-center gap-2.5 rounded-lg border p-2.5 cursor-pointer transition-colors hover:bg-muted/50"
                    >
                      <Checkbox
                        checked={enabled}
                        onCheckedChange={() => toggleSignal(signal)}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium">{signal.replace(/_/g, " ")}</p>
                      </div>
                      <Badge variant={enabled ? "default" : "secondary"} className="!text-[8px] !h-4">
                        {enabled ? "on" : "off"}
                      </Badge>
                    </label>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground italic">
                {isCoordinator
                  ? "The coordinator processes all signals from connected agents."
                  : "Add signal types in the General tab or when creating the agent."}
              </p>
            )}

            {data.isCustom && (
              <>
                <Separator />
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium">Add Custom Signal</Label>
                  <div className="flex gap-2">
                    <Input
                      placeholder="signal_name"
                      className="h-8 text-xs flex-1"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          const val = (e.target as HTMLInputElement).value.trim().toLowerCase().replace(/\s+/g, "_");
                          if (val && !config.enabledSignals.includes(val)) {
                            updateConfig({ enabledSignals: [...config.enabledSignals, val] });
                            onUpdate({ signals: [...data.signals, val] });
                            (e.target as HTMLInputElement).value = "";
                          }
                        }
                      }}
                    />
                  </div>
                </div>
              </>
            )}
          </TabsContent>

          {/* Thresholds/Tuning tab */}
          <TabsContent value="thresholds" className="px-4 pb-4 space-y-4 mt-0">
            <div className="space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Confidence Floor</Label>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {config.confidenceFloor.toFixed(2)}
                  </span>
                </div>
                <Slider
                  value={[config.confidenceFloor]}
                  onValueChange={([v]) => updateConfig({ confidenceFloor: v })}
                  min={0} max={1} step={0.05}
                  className="w-full"
                />
                <p className="text-[10px] text-muted-foreground">
                  Findings below this confidence score are suppressed.
                </p>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Max Candidates</Label>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {config.maxCandidates}
                  </span>
                </div>
                <Slider
                  value={[config.maxCandidates]}
                  onValueChange={([v]) => updateConfig({ maxCandidates: v })}
                  min={1} max={20} step={1}
                  className="w-full"
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Min Severity</Label>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {config.minSeverity.toFixed(2)}
                  </span>
                </div>
                <Slider
                  value={[config.minSeverity]}
                  onValueChange={([v]) => updateConfig({ minSeverity: v })}
                  min={0} max={1} step={0.05}
                  className="w-full"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">Cost per {data.meter}</Label>
                <Input
                  type="number"
                  value={config.costPerUnit || ""}
                  onChange={(e) => updateConfig({ costPerUnit: Number.parseFloat(e.target.value) || 0 })}
                  className="h-8 text-xs"
                  placeholder="Use default rate"
                  step="0.01"
                />
                <p className="text-[10px] text-muted-foreground">
                  Override the default pricing rate. Leave empty for cloud reference rate.
                </p>
              </div>
            </div>

            {thresholdDefs.length > 0 && (
              <>
                <Separator />
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Domain Thresholds
                </h4>
                <div className="space-y-3">
                  {thresholdDefs.map((t) => (
                    <div key={t.label} className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <Label className="text-xs">{t.label}</Label>
                        <span className="text-[10px] font-mono text-muted-foreground">
                          {(config.customThresholds[t.label] ?? t.default).toFixed(
                            t.step < 1 ? 2 : 0,
                          )}
                        </span>
                      </div>
                      <Slider
                        value={[config.customThresholds[t.label] ?? t.default]}
                        onValueChange={([v]) => updateThreshold(t.label, v)}
                        min={t.min} max={t.max} step={t.step}
                        className="w-full"
                      />
                    </div>
                  ))}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full text-[10px] gap-1.5"
                  onClick={() => {
                    const defaults: Record<string, number> = {};
                    for (const t of thresholdDefs) defaults[t.label] = t.default;
                    updateConfig({ customThresholds: defaults });
                  }}
                >
                  <RotateCcw className="size-3" /> Reset to defaults
                </Button>
              </>
            )}
          </TabsContent>

          {/* Alerts tab */}
          <TabsContent value="alerts" className="px-4 pb-4 space-y-4 mt-0">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs">Enable Alerts</Label>
                <Switch
                  checked={config.alertsEnabled}
                  onCheckedChange={(v) => updateConfig({ alertsEnabled: v })}
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">Alert Channels</Label>
                <div className="space-y-1.5">
                  {["dashboard", "slack", "email", "webhook"].map((ch) => {
                    const active = config.alertChannels.includes(ch);
                    return (
                      <label key={ch} className="flex items-center gap-2 cursor-pointer">
                        <Checkbox
                          checked={active}
                          onCheckedChange={(checked) => {
                            const next = checked
                              ? [...config.alertChannels, ch]
                              : config.alertChannels.filter((c) => c !== ch);
                            updateConfig({ alertChannels: next });
                          }}
                        />
                        <span className="text-xs capitalize">{ch}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs">Min Severity for Alert</Label>
                <Select
                  value={config.alertSeverityThreshold}
                  onValueChange={(v) =>
                    updateConfig({ alertSeverityThreshold: v as "low" | "medium" | "high" })
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low" className="text-xs">Low — all findings</SelectItem>
                    <SelectItem value="medium" className="text-xs">Medium — significant only</SelectItem>
                    <SelectItem value="high" className="text-xs">High — critical only</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Auto-approve</Label>
                  <Switch
                    checked={config.autoApproveEnabled}
                    onCheckedChange={(v) => updateConfig({ autoApproveEnabled: v })}
                  />
                </div>
                {config.autoApproveEnabled && (
                  <div className="space-y-1.5">
                    <Label className="text-xs">Max auto-approve value ($/mo)</Label>
                    <Input
                      type="number"
                      value={config.autoApproveMaxValue}
                      onChange={(e) =>
                        updateConfig({ autoApproveMaxValue: Number.parseFloat(e.target.value) || 0 })
                      }
                      className="h-8 text-xs"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Findings below this monthly value are auto-approved without human review.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </TabsContent>
        </ScrollArea>
      </Tabs>

      {/* Footer actions */}
      <div className="flex items-center gap-2 border-t px-4 py-3">
        <Button
          size="sm"
          className="flex-1 gap-1.5"
          variant="default"
          onClick={() =>
            onUpdate({ status: data.status === "active" ? "paused" : "active" })
          }
        >
          {data.status === "active" ? (
            <><PauseIcon className="size-3.5" /> Pause</>
          ) : (
            <><PlayIcon className="size-3.5" /> Activate</>
          )}
        </Button>
        <Button size="sm" variant="outline" className="gap-1.5" onClick={onDuplicate} title="Duplicate">
          <Copy className="size-3.5" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5 text-destructive hover:text-destructive"
          onClick={onDelete}
          title="Delete"
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

function TriggerDetail({
  data, onClose, onUpdate, onDelete,
}: {
  data: TriggerNodeData;
  onClose: () => void;
  onUpdate: (d: Partial<TriggerNodeData>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h3 className="text-sm font-semibold">{data.label}</h3>
        <Button variant="ghost" size="icon" className="size-7" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="px-4 py-3 space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Label</Label>
            <Input
              value={data.label}
              onChange={(e) => onUpdate({ label: e.target.value })}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Type</Label>
            <Select value={data.type} onValueChange={(v) => onUpdate({ type: v as TriggerNodeData["type"] })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cron" className="text-xs">Cron</SelectItem>
                <SelectItem value="webhook" className="text-xs">Webhook</SelectItem>
                <SelectItem value="manual" className="text-xs">Manual</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Schedule</Label>
            <Input
              value={data.schedule}
              onChange={(e) => onUpdate({ schedule: e.target.value })}
              className="h-8 text-xs"
            />
          </div>
        </div>
      </ScrollArea>
      <div className="flex items-center gap-2 border-t px-4 py-3">
        <Button size="sm" variant="outline" className="flex-1 gap-1.5 text-destructive hover:text-destructive" onClick={onDelete}>
          <Trash2 className="size-3.5" /> Remove
        </Button>
      </div>
    </div>
  );
}

function OutputDetail({
  data, onClose, onUpdate, onDelete,
}: {
  data: OutputNodeData;
  onClose: () => void;
  onUpdate: (d: Partial<OutputNodeData>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h3 className="text-sm font-semibold">{data.label}</h3>
        <Button variant="ghost" size="icon" className="size-7" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="px-4 py-3 space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Label</Label>
            <Input
              value={data.label}
              onChange={(e) => onUpdate({ label: e.target.value })}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Type</Label>
            <Select value={data.type} onValueChange={(v) => onUpdate({ type: v as OutputNodeData["type"] })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="dashboard" className="text-xs">Dashboard</SelectItem>
                <SelectItem value="slack" className="text-xs">Slack</SelectItem>
                <SelectItem value="webhook" className="text-xs">Webhook</SelectItem>
                <SelectItem value="email" className="text-xs">Email</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Destination</Label>
            <Input
              value={data.destination}
              onChange={(e) => onUpdate({ destination: e.target.value })}
              className="h-8 text-xs"
              placeholder="#channel, URL, or email"
            />
          </div>
        </div>
      </ScrollArea>
      <div className="flex items-center gap-2 border-t px-4 py-3">
        <Button size="sm" variant="outline" className="flex-1 gap-1.5 text-destructive hover:text-destructive" onClick={onDelete}>
          <Trash2 className="size-3.5" /> Remove
        </Button>
      </div>
    </div>
  );
}
