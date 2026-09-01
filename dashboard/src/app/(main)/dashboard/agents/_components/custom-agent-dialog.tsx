"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { X } from "lucide-react";
import type { AgentDomain, CatalogEntry } from "./agent-data";

const AVAILABLE_DOMAINS: { value: AgentDomain; label: string }[] = [
  { value: "scheduling", label: "Scheduling" },
  { value: "storage", label: "Storage" },
  { value: "network", label: "Network" },
  { value: "commitments", label: "Commitments" },
  { value: "power", label: "Power / Thermal" },
  { value: "training", label: "Training" },
  { value: "inference", label: "Inference" },
  { value: "custom", label: "Custom" },
];

const METER_OPTIONS = [
  "GPU-h", "GB-month", "GB", "$ committed", "kWh", "replica-h", "CPU-h", "custom",
];

interface CustomAgentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreateAgent: (entry: CatalogEntry) => void;
}

export function CustomAgentDialog({ open, onOpenChange, onCreateAgent }: CustomAgentDialogProps) {
  const [name, setName] = useState("");
  const [domain, setDomain] = useState<AgentDomain>("custom");
  const [meter, setMeter] = useState("custom");
  const [customMeter, setCustomMeter] = useState("");
  const [description, setDescription] = useState("");
  const [signalInput, setSignalInput] = useState("");
  const [signals, setSignals] = useState<string[]>([]);

  const addSignal = () => {
    const trimmed = signalInput.trim().toLowerCase().replace(/\s+/g, "_");
    if (trimmed && !signals.includes(trimmed)) {
      setSignals([...signals, trimmed]);
      setSignalInput("");
    }
  };

  const removeSignal = (s: string) => {
    setSignals(signals.filter((sig) => sig !== s));
  };

  const handleCreate = () => {
    if (!name.trim()) return;
    const id = `custom_${name.trim().toLowerCase().replace(/\s+/g, "_")}_agent`;
    const entry: CatalogEntry = {
      id,
      label: name.trim(),
      domain,
      meter: meter === "custom" ? customMeter || "custom" : meter,
      signals,
      description: description || `Custom agent: ${name.trim()}`,
      builtin: false,
    };
    onCreateAgent(entry);
    onOpenChange(false);
    setName("");
    setDomain("custom");
    setMeter("custom");
    setCustomMeter("");
    setDescription("");
    setSignals([]);
    setSignalInput("");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create Custom Agent</DialogTitle>
          <DialogDescription className="text-xs">
            Define a new agent with its own domain, meter, and signal types.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Agent Name</Label>
            <Input
              placeholder="e.g. Cost Anomaly Detector"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-8 text-xs"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Domain</Label>
              <Select value={domain} onValueChange={(v) => setDomain(v as AgentDomain)}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AVAILABLE_DOMAINS.map((d) => (
                    <SelectItem key={d.value} value={d.value} className="text-xs">
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Meter</Label>
              <Select value={meter} onValueChange={setMeter}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {METER_OPTIONS.map((m) => (
                    <SelectItem key={m} value={m} className="text-xs">
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {meter === "custom" && (
            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Custom Meter Unit</Label>
              <Input
                placeholder="e.g. requests/s, jobs, $"
                value={customMeter}
                onChange={(e) => setCustomMeter(e.target.value)}
                className="h-8 text-xs"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Signal Types</Label>
            <div className="flex gap-2">
              <Input
                placeholder="e.g. cost_spike"
                value={signalInput}
                onChange={(e) => setSignalInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSignal(); } }}
                className="h-8 text-xs flex-1"
              />
              <Button size="sm" variant="outline" className="h-8 text-xs" onClick={addSignal}>
                Add
              </Button>
            </div>
            {signals.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                {signals.map((s) => (
                  <Badge key={s} variant="secondary" className="text-[10px] gap-1 pr-1">
                    {s.replace(/_/g, " ")}
                    <button type="button" onClick={() => removeSignal(s)} className="hover:text-destructive">
                      <X className="size-2.5" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Description</Label>
            <Textarea
              placeholder="What does this agent detect?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="text-xs min-h-[60px] resize-none"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleCreate} disabled={!name.trim()}>
            Create & Add to Canvas
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
