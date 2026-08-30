"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  useTable,
} from "@tanstack/react-table";
import type { ColumnDef } from "@tanstack/react-table";
import { Subscribe } from "@tanstack/react-table";
import { ChevronDownIcon, ListFilter } from "lucide-react";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { dataTableFeatures, type DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

import nodesData from "./nodes-data.json";

const nodeSchema = z.object({
  id: z.string(),
  cluster: z.string(),
  gpus: z.number(),
  model: z.string(),
  status: z.string(),
  utilization: z.number(),
  jobs: z.number(),
  findings: z.number(),
  last_seen: z.string(),
});
type NodeRow = z.infer<typeof nodeSchema>;
const nodes = z.array(nodeSchema).parse(nodesData);

const statusStyles: Record<string, string> = {
  healthy: "border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-300",
  warning: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  critical: "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300",
  maintenance: "border-gray-400/20 bg-gray-400/10 text-gray-600 dark:text-gray-400",
};

const clusterOptions = ["all", "aws-us-east-1", "gcp-europe-west4", "azure-eastus", "on-prem-dc1"] as const;
const statusOptions = ["all", "healthy", "warning", "critical", "maintenance"] as const;

const nodeColumns: ColumnDef<DataTableFeatures, NodeRow>[] = [
  {
    id: "select",
    header: ({ table }) => (
      <Subscribe source={table.atoms.rowSelection} selector={() => (table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && "indeterminate")) as boolean | "indeterminate"}>
        {(checked) => <Checkbox checked={checked} onCheckedChange={(v) => table.toggleAllPageRowsSelected(!!v)} aria-label="Select all" />}
      </Subscribe>
    ),
    cell: ({ row }) => (
      <Subscribe source={row.table.atoms.rowSelection} selector={(sel) => Boolean(sel?.[row.id])}>
        {(checked) => <Checkbox checked={checked} onCheckedChange={(v) => row.toggleSelected(!!v)} aria-label={`Select ${row.original.id}`} />}
      </Subscribe>
    ),
    enableHiding: false,
  },
  { accessorKey: "id", header: "Node", cell: ({ row }) => <div className="font-mono text-sm">{row.original.id}</div>, enableHiding: false },
  { accessorKey: "cluster", header: "Cluster", cell: ({ row }) => <div className="text-sm">{row.original.cluster}</div>, filterFn: "equalsString" },
  { accessorKey: "model", header: "Model", cell: ({ row }) => <div className="text-sm text-muted-foreground">{row.original.model}</div> },
  { accessorKey: "gpus", header: "GPUs", cell: ({ row }) => <div className="text-sm tabular-nums">{row.original.gpus}</div> },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => {
      const s = row.original.status;
      return <Badge variant="outline" className={cn("rounded-full px-2.5 text-xs capitalize", statusStyles[s])}>{s}</Badge>;
    },
    filterFn: "equalsString",
  },
  {
    accessorKey: "utilization",
    header: "Utilization",
    cell: ({ row }) => {
      const u = row.original.utilization;
      return (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
            <div className="h-full rounded-full bg-emerald-500" style={{ width: `${u}%` }} />
          </div>
          <span className="text-sm tabular-nums">{u}%</span>
        </div>
      );
    },
  },
  { accessorKey: "jobs", header: "Jobs", cell: ({ row }) => <div className="text-sm tabular-nums">{row.original.jobs}</div> },
  { accessorKey: "findings", header: "Findings", cell: ({ row }) => <div className="font-medium text-sm tabular-nums">{row.original.findings}</div> },
  { accessorKey: "last_seen", header: "Last Seen", cell: ({ row }) => <div className="text-sm text-muted-foreground">{row.original.last_seen}</div> },
];

function preventNav(e: React.MouseEvent<HTMLAnchorElement>) { e.preventDefault(); }

export function ClusterNodesSection() {
  const [rowSelection, setRowSelection] = React.useState({});
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility] = React.useState<ColumnVisibilityState>({});
  const [globalFilter, setGlobalFilter] = React.useState("");
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const table = useTable({
    features: dataTableFeatures,
    data: nodes,
    columns: nodeColumns,
    state: { rowSelection, columnFilters, columnVisibility, globalFilter, pagination },
    getRowId: (row) => row.id,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onPaginationChange: setPagination,
    globalFilterFn: "includesString",
  });

  const clusterFilter = (table.getColumn("cluster")?.getFilterValue() as string | undefined) ?? "all";
  const statusFilter = (table.getColumn("status")?.getFilterValue() as string | undefined) ?? "all";
  const currentPage = table.state.pagination.pageIndex + 1;
  const pageCount = table.getPageCount();
  const filteredCount = table.getFilteredRowModel().rows.length;

  const pageNumbers = React.useMemo(() => {
    if (pageCount <= 3) return Array.from({ length: pageCount }, (_, i) => i + 1);
    if (currentPage <= 2) return [1, 2, 3];
    if (currentPage >= pageCount - 1) return [pageCount - 2, pageCount - 1, pageCount];
    return [currentPage - 1, currentPage, currentPage + 1];
  }, [currentPage, pageCount]);

  return (
    <section>
      <Card>
        <CardHeader>
          <CardTitle className="leading-none">Cluster Nodes</CardTitle>
          <CardDescription>All compute nodes across registered clusters with real-time status and utilization.</CardDescription>
          <CardAction>
            <div className="flex items-center gap-2">
              <Input
                className="h-7 w-44 md:w-52"
                placeholder="Search nodes..."
                value={table.state.globalFilter ?? ""}
                onChange={(e) => { table.setGlobalFilter(e.target.value || undefined); table.setPageIndex(0); }}
              />
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <ListFilter data-icon="inline-start" />Cluster<ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuRadioGroup value={clusterFilter} onValueChange={(v) => { table.getColumn("cluster")?.setFilterValue(v === "all" ? undefined : v); table.setPageIndex(0); }}>
                    {clusterOptions.map((o) => (
                      <DropdownMenuRadioItem key={o} value={o}>{o === "all" ? "All clusters" : o}</DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <ListFilter data-icon="inline-start" />Status<ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuRadioGroup value={statusFilter} onValueChange={(v) => { table.getColumn("status")?.setFilterValue(v === "all" ? undefined : v); table.setPageIndex(0); }}>
                    {statusOptions.map((o) => (
                      <DropdownMenuRadioItem key={o} value={o} className="capitalize">{o === "all" ? "All status" : o}</DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 px-0">
          <div className="overflow-hidden">
            <Table className="**:data-[slot='table-cell']:px-4 **:data-[slot='table-head']:px-4 **:data-[slot='table-cell']:py-3">
              <TableHeader className="border-t **:data-[slot='table-head']:h-11 **:data-[slot='table-head']:font-medium **:data-[slot='table-head']:text-foreground **:data-[slot='table-head']:text-sm">
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id}>
                    {hg.headers.map((h) => (
                      <TableHead key={h.id} colSpan={h.colSpan}>{h.isPlaceholder ? null : <table.FlexRender header={h} />}</TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody className="**:data-[slot='table-row']:border-border/50 **:data-[slot='table-row']:hover:bg-transparent">
                {table.getRowModel().rows.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow key={row.id} data-state={table.state.rowSelection[row.id] && "selected"}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}><table.FlexRender cell={cell} /></TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={table.getVisibleLeafColumns().length} className="h-24 text-center">No results.</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 pb-1">
            <p className="text-muted-foreground text-sm">{filteredCount} nodes</p>
            <Pagination className="mx-0 w-auto justify-end">
              <PaginationContent className="gap-1.5">
                <PaginationItem>
                  <PaginationPrevious href="#" className={!table.getCanPreviousPage() ? "pointer-events-none opacity-50" : undefined} onClick={(e) => { preventNav(e); table.previousPage(); }} />
                </PaginationItem>
                {pageNumbers[0] > 1 ? <PaginationItem><PaginationEllipsis /></PaginationItem> : null}
                {pageNumbers.map((n) => (
                  <PaginationItem key={n}>
                    <PaginationLink href="#" isActive={table.state.pagination.pageIndex === n - 1} onClick={(e) => { preventNav(e); table.setPageIndex(n - 1); }}>{n}</PaginationLink>
                  </PaginationItem>
                ))}
                {pageNumbers[pageNumbers.length - 1] < pageCount ? <PaginationItem><PaginationEllipsis /></PaginationItem> : null}
                <PaginationItem>
                  <PaginationNext href="#" className={!table.getCanNextPage() ? "pointer-events-none opacity-50" : undefined} onClick={(e) => { preventNav(e); table.nextPage(); }} />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
