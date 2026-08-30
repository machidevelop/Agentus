"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { Subscribe } from "@tanstack/react-table";
import { Pencil } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

import type { FindingRow } from "./schema";

const healthStripSlots = Array.from({ length: 18 }, (_, index) => ({
  id: `strip-${index + 1}`,
  threshold: index + 1,
}));

function getHealthScore(health: FindingRow["health"]) {
  switch (health) {
    case "On Track":
      return 18;
    case "Needs Review":
      return 11;
    case "At Risk":
      return 7;
    default:
      return 0;
  }
}

function getTypeBadgeClass(type: string) {
  switch (type) {
    case "idle_allocation":
      return "border-amber-200 bg-amber-500/10 text-amber-700 dark:border-amber-900/40 dark:bg-amber-500/15 dark:text-amber-300";
    case "queue_inefficiency":
      return "border-blue-200 bg-blue-500/10 text-blue-700 dark:border-blue-900/40 dark:bg-blue-500/15 dark:text-blue-300";
    case "over_allocation":
      return "border-purple-200 bg-purple-500/10 text-purple-700 dark:border-purple-900/40 dark:bg-purple-500/15 dark:text-purple-300";
    case "fragmentation":
      return "border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300";
    default:
      return "";
  }
}

function getConfidenceBadgeClass(level: string) {
  switch (level) {
    case "high":
      return "border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300";
    case "medium":
      return "border-amber-200 bg-amber-500/10 text-amber-700 dark:border-amber-900/40 dark:bg-amber-500/15 dark:text-amber-300";
    case "low":
      return "border-destructive/20 bg-destructive/10 text-destructive";
    default:
      return "";
  }
}

function getVerdictBadgeClass(verdict: string) {
  switch (verdict) {
    case "LIKELY_VALID":
      return "border-green-200 bg-green-500/10 text-green-700 dark:border-green-900/40 dark:bg-green-500/15 dark:text-green-300";
    case "REVIEW":
      return "border-amber-200 bg-amber-500/10 text-amber-700 dark:border-amber-900/40 dark:bg-amber-500/15 dark:text-amber-300";
    default:
      return "";
  }
}

export const findingsColumns: ColumnDef<DataTableFeatures, FindingRow>[] = [
  {
    id: "select",
    header: ({ table }) => (
      <Subscribe
        source={table.atoms.rowSelection}
        selector={() =>
          table.getIsAllPageRowsSelected() ||
          (table.getIsSomePageRowsSelected() && !table.getIsAllPageRowsSelected() && "indeterminate")
        }
      >
        {(checked) => (
          <Checkbox
            checked={checked}
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
            aria-label="Select all findings"
          />
        )}
      </Subscribe>
    ),
    cell: ({ row }) => (
      <Subscribe source={row.table.atoms.rowSelection} selector={(selection) => Boolean(selection?.[row.id])}>
        {(checked) => (
          <Checkbox
            checked={checked}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            aria-label={`Select ${row.original.id}`}
          />
        )}
      </Subscribe>
    ),
    enableHiding: false,
  },
  {
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => (
      <div className="font-mono text-sm tracking-tight">{row.original.id}</div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: "type",
    header: "Type",
    cell: ({ row }) => (
      <Badge variant="outline" className={cn("rounded-full px-2.5", getTypeBadgeClass(row.original.type))}>
        {row.original.type.replace("_", " ")}
      </Badge>
    ),
    filterFn: "equalsString",
  },
  {
    accessorKey: "confidence_level",
    header: "Confidence",
    cell: ({ row }) => (
      <Badge variant="outline" className={cn("rounded-full px-2.5", getConfidenceBadgeClass(row.original.confidence_level))}>
        {row.original.confidence_level}
      </Badge>
    ),
    filterFn: "equalsString",
  },
  {
    accessorKey: "health",
    header: "Signal",
    cell: ({ row }) => (
      <div className="flex items-end gap-0.5" title={row.original.health}>
        <span className="sr-only">{row.original.health}</span>
        {healthStripSlots.map((slot) => (
          <div
            key={`${row.original.id}-${slot.id}`}
            className={cn(
              "h-5 w-1 rounded-full",
              slot.threshold <= getHealthScore(row.original.health) ? "bg-green-500/85" : "bg-green-500/15",
            )}
          />
        ))}
      </div>
    ),
    filterFn: "equalsString",
  },
  {
    accessorKey: "monthly_value",
    header: "Monthly Value",
    cell: ({ row }) => (
      <div className="font-medium text-sm tabular-nums">{row.original.monthly_value}</div>
    ),
  },
  {
    accessorKey: "verdict",
    header: "Verdict",
    cell: ({ row }) => (
      <Badge variant="outline" className={cn("rounded-full px-2.5", getVerdictBadgeClass(row.original.verdict))}>
        {row.original.verdict}
      </Badge>
    ),
  },
  {
    id: "actions",
    header: () => <div className="text-right">Edit</div>,
    cell: () => (
      <div className="text-right">
        <Button
          variant="ghost"
          size="icon"
          className="size-8 rounded-full text-muted-foreground hover:bg-transparent focus-visible:bg-transparent"
        >
          <Pencil />
          <span className="sr-only">Edit finding</span>
        </Button>
      </div>
    ),
    enableHiding: false,
  },
];
