"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { Subscribe } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

import type { FindingSummary } from "./schema";

const typeStyles: Record<string, string> = {
  idle_allocation: "border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  queue_inefficiency: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  over_allocation: "border-purple-500/20 bg-purple-500/10 text-purple-700 dark:text-purple-300",
  fragmentation: "border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300",
};

const verdictStyles: Record<string, string> = {
  LIKELY_VALID: "border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300",
  REVIEW: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  INVALID: "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300",
};

const typeLabels: Record<string, string> = {
  idle_allocation: "Idle",
  queue_inefficiency: "Queue",
  over_allocation: "Over-alloc",
  fragmentation: "Fragment",
};

export const columns: ColumnDef<DataTableFeatures, FindingSummary>[] = [
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
          <Checkbox
            checked={checked}
            onCheckedChange={(v) => table.toggleAllPageRowsSelected(!!v)}
            aria-label="Select all"
          />
        )}
      </Subscribe>
    ),
    cell: ({ row }) => (
      <Subscribe source={row.table.atoms.rowSelection} selector={(sel) => Boolean(sel?.[row.id])}>
        {(checked) => (
          <Checkbox
            checked={checked}
            onCheckedChange={(v) => row.toggleSelected(!!v)}
            aria-label="Select row"
          />
        )}
      </Subscribe>
    ),
    enableSorting: false,
    enableHiding: false,
  },
  {
    accessorKey: "id",
    header: "ID",
    cell: ({ row }) => <span className="font-mono text-muted-foreground text-xs">{row.getValue("id")}</span>,
  },
  {
    accessorKey: "job_id",
    header: "Job",
    cell: ({ row }) => <span className="font-mono text-xs">{row.getValue("job_id")}</span>,
  },
  {
    accessorKey: "type",
    header: "Type",
    cell: ({ row }) => {
      const t = row.getValue("type") as string;
      return (
        <Badge className={cn("rounded-sm border text-xs", typeStyles[t])} variant="outline">
          {typeLabels[t] ?? t}
        </Badge>
      );
    },
    filterFn: (row, id, value) => value.includes(row.getValue(id)),
  },
  {
    accessorKey: "confidence",
    header: "Conf.",
    cell: ({ row }) => {
      const c = row.getValue("confidence") as string;
      return <span className="capitalize text-sm text-muted-foreground">{c}</span>;
    },
    filterFn: (row, id, value) => value.includes(row.getValue(id)),
  },
  {
    accessorKey: "value",
    header: "Value",
    cell: ({ row }) => {
      const v = row.getValue("value") as number;
      return <span className="font-mono text-sm">${v.toLocaleString()}</span>;
    },
  },
  {
    accessorKey: "verdict",
    header: "Verdict",
    cell: ({ row }) => {
      const v = row.getValue("verdict") as string;
      return (
        <Badge className={cn("rounded-sm border text-xs", verdictStyles[v])} variant="outline">
          {v}
        </Badge>
      );
    },
    filterFn: (row, id, value) => value.includes(row.getValue(id)),
  },
  {
    accessorKey: "detected",
    header: "Detected",
    cell: ({ row }) => <span className="text-muted-foreground text-xs">{row.getValue("detected")}</span>,
  },
  {
    id: "search",
    accessorFn: (row) => `${row.id} ${row.job_id} ${row.type} ${row.verdict}`,
    header: "",
    enableHiding: false,
    enableSorting: false,
    meta: { hidden: true },
  },
];
