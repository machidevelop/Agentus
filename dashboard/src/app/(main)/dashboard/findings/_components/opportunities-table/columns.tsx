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

const healthStripSlots = Array.from({ length: 18 }, (_, index) => ({ id: `strip-${index + 1}`, threshold: index + 1 }));

function getHealthScore(health: FindingRow["health"]) {
  switch (health) {
    case "High Confidence": return 18;
    case "Medium Confidence": return 11;
    case "Low Confidence": return 7;
    case "Dismissed": return 3;
    default: return 0;
  }
}

const typeStyles: Record<string, string> = {
  idle_allocation: "border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  queue_inefficiency: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  over_allocation: "border-purple-500/20 bg-purple-500/10 text-purple-700 dark:text-purple-300",
  fragmentation: "border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300",
};

const statusStyles: Record<string, string> = {
  open: "border-blue-500/20 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  in_review: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  resolved: "border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300",
  dismissed: "border-muted-foreground/20 bg-muted/50 text-muted-foreground",
};

export const findingsColumns: ColumnDef<DataTableFeatures, FindingRow>[] = [
  {
    id: "select",
    header: ({ table }) => (
      <Subscribe
        source={table.atoms.rowSelection}
        selector={() =>
          (table.getIsAllPageRowsSelected() ||
          (table.getIsSomePageRowsSelected() && "indeterminate")) as boolean | "indeterminate"
        }
      >
        {(checked) => (
          <Checkbox checked={checked} onCheckedChange={(v) => table.toggleAllPageRowsSelected(!!v)} aria-label="Select all" />
        )}
      </Subscribe>
    ),
    cell: ({ row }) => (
      <Subscribe source={row.table.atoms.rowSelection} selector={(sel) => Boolean(sel?.[row.id])}>
        {(checked) => (
          <Checkbox checked={checked} onCheckedChange={(v) => row.toggleSelected(!!v)} aria-label={`Select ${row.original.id}`} />
        )}
      </Subscribe>
    ),
    enableHiding: false,
  },
  {
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => <div className="font-mono text-sm text-muted-foreground">{row.original.id}</div>,
    enableHiding: false,
  },
  {
    accessorKey: "job_id",
    header: "Job",
    cell: ({ row }) => <div className="font-mono text-sm">{row.original.job_id}</div>,
  },
  {
    accessorKey: "cluster",
    header: "Cluster",
    cell: ({ row }) => <div className="text-sm">{row.original.cluster}</div>,
    filterFn: "equalsString",
  },
  {
    accessorKey: "type",
    header: "Type",
    cell: ({ row }) => {
      const t = row.original.type;
      return (
        <Badge variant="outline" className={cn("rounded-sm text-xs", typeStyles[t])}>
          {t.replace(/_/g, " ")}
        </Badge>
      );
    },
    filterFn: "equalsString",
  },
  {
    accessorKey: "health",
    header: "Confidence",
    cell: ({ row }) => (
      <div className="flex items-end gap-0.5" title={row.original.health}>
        <span className="sr-only">{row.original.health}</span>
        {healthStripSlots.map((slot) => (
          <div
            key={`${row.original.id}-${slot.id}`}
            className={cn(
              "h-5 w-1 rounded-full",
              slot.threshold <= getHealthScore(row.original.health) ? "bg-emerald-500/85" : "bg-emerald-500/15"
            )}
          />
        ))}
      </div>
    ),
    filterFn: "equalsString",
  },
  {
    accessorKey: "value",
    header: "Est. Value",
    cell: ({ row }) => <div className="font-medium text-sm tabular-nums">{row.original.value}</div>,
  },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => {
      const s = row.original.status;
      return (
        <Badge variant="outline" className={cn("rounded-full px-2.5 text-xs", statusStyles[s])}>
          {s.replace(/_/g, " ")}
        </Badge>
      );
    },
    filterFn: "equalsString",
  },
  {
    accessorKey: "detected",
    header: "Detected",
    cell: ({ row }) => <div className="text-sm text-muted-foreground">{row.original.detected}</div>,
  },
  {
    id: "actions",
    header: () => <div className="text-right">Edit</div>,
    cell: () => (
      <div className="text-right">
        <Button variant="ghost" size="icon" className="size-8 rounded-full text-muted-foreground hover:bg-transparent focus-visible:bg-transparent">
          <Pencil />
          <span className="sr-only">Edit finding</span>
        </Button>
      </div>
    ),
    enableHiding: false,
  },
];
