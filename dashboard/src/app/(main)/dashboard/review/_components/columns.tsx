"use client";

import type { Column, ColumnDef } from "@tanstack/react-table";
import { Subscribe } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, MoreHorizontal, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

import { confidences, labels, types, type Review } from "./data";

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

function SortIcon({ sortDirection }: { sortDirection: false | "asc" | "desc" }) {
  if (sortDirection === "desc") return <ArrowDown data-icon="inline-end" />;
  if (sortDirection === "asc") return <ArrowUp data-icon="inline-end" />;
  return <ArrowUpDown data-icon="inline-end" />;
}

function TitleColumnHeader({ column }: { column: Column<DataTableFeatures, Review, unknown> }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="-ml-3 text-muted-foreground data-[state=open]:bg-accent">
          Description
          <SortIcon sortDirection={column.getIsSorted()} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={() => column.toggleSorting(false)}>
          <ArrowUp />
          Asc
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => column.toggleSorting(true)}>
          <ArrowDown />
          Desc
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => column.clearSorting()}>
          <RotateCcw />
          Reset
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export const columns: ColumnDef<DataTableFeatures, Review>[] = [
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
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
            aria-label="Select all"
            className="translate-y-0.5"
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
            aria-label="Select row"
            className="translate-y-0.5"
          />
        )}
      </Subscribe>
    ),
    enableSorting: false,
    enableHiding: false,
  },
  {
    accessorKey: "id",
    header: "Finding",
    cell: ({ row }) => <div className="w-24 font-mono text-muted-foreground text-sm">{row.getValue("id")}</div>,
    enableSorting: false,
    enableHiding: false,
  },
  {
    accessorKey: "title",
    header: ({ column }) => <TitleColumnHeader column={column} />,
    cell: ({ row }) => {
      const label = labels.find((l) => l.value === row.original.label);
      return (
        <div className="flex min-w-0 items-center gap-2">
          {label && (
            <Badge className="rounded-sm bg-transparent" variant="outline">
              {label.label}
            </Badge>
          )}
          <span className="max-w-lg truncate font-medium text-sm">{row.getValue("title")}</span>
        </div>
      );
    },
  },
  {
    accessorKey: "type",
    header: "Type",
    cell: ({ row }) => {
      const type = types.find((t) => t.value === row.getValue("type"));
      if (!type) return null;
      return (
        <Badge className={cn("gap-1.5 rounded-sm border font-medium", typeStyles[type.value])} variant="outline">
          {type.icon && <type.icon className="size-4" />}
          {type.label}
        </Badge>
      );
    },
    filterFn: (row, id, value) => value.includes(row.getValue(id)),
  },
  {
    accessorKey: "confidence",
    header: "Confidence",
    cell: ({ row }) => {
      const conf = confidences.find((c) => c.value === row.getValue("confidence"));
      if (!conf) return null;
      return (
        <div className="flex items-center gap-2 text-sm">
          {conf.icon && <conf.icon className="size-4 text-muted-foreground" />}
          {conf.label}
        </div>
      );
    },
    filterFn: (row, id, value) => value.includes(row.getValue(id)),
  },
  {
    accessorKey: "verdict",
    header: "Verdict",
    cell: ({ row }) => {
      const verdict = row.getValue("verdict") as string;
      return (
        <Badge className={cn("gap-1 rounded-sm border font-medium", verdictStyles[verdict] ?? "")} variant="outline">
          {verdict}
        </Badge>
      );
    },
    filterFn: (row, id, value) => value.includes(row.getValue(id)),
  },
  {
    id: "actions",
    cell: ({ row }) => {
      const review = row.original as Review;
      return (
        <div className="text-right">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="text-muted-foreground data-[state=open]:bg-muted">
                <MoreHorizontal />
                <span className="sr-only">Open menu</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem>Mark Valid</DropdownMenuItem>
              <DropdownMenuItem>Mark for Review</DropdownMenuItem>
              <DropdownMenuItem>Mark Invalid</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem>Copy ID</DropdownMenuItem>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>Labels</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  <DropdownMenuRadioGroup value={review.label}>
                    {labels.map((label) => (
                      <DropdownMenuRadioItem key={label.value} value={label.value}>
                        {label.label}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
              <DropdownMenuSeparator />
              <DropdownMenuItem>View Details</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      );
    },
  },
];
