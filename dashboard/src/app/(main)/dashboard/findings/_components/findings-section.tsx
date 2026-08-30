"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  useTable,
} from "@tanstack/react-table";
import { ChevronDownIcon, ListFilter } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { dataTableFeatures } from "@/lib/data-table-features";

import { findingsColumns } from "./opportunities-table/columns";
import findingsData from "./opportunities-table/data.json";
import { findingsSchema } from "./opportunities-table/schema";

const typeOptions = ["all", "idle_allocation", "queue_inefficiency", "over_allocation", "fragmentation"] as const;
const healthOptions = ["all", "High Confidence", "Medium Confidence", "Low Confidence", "Dismissed"] as const;
const findings = findingsSchema.parse(findingsData);

function preventNav(e: React.MouseEvent<HTMLAnchorElement>) { e.preventDefault(); }

export function FindingsSection() {
  const [rowSelection, setRowSelection] = React.useState({});
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility] = React.useState<ColumnVisibilityState>({});
  const [globalFilter, setGlobalFilter] = React.useState("");
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const table = useTable({
    features: dataTableFeatures,
    data: findings,
    columns: findingsColumns,
    state: { rowSelection, columnFilters, columnVisibility, globalFilter, pagination },
    getRowId: (row) => row.id,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onPaginationChange: setPagination,
    globalFilterFn: "includesString",
  });

  const searchQuery = table.state.globalFilter ?? "";
  const typeFilter = (table.getColumn("type")?.getFilterValue() as string | undefined) ?? "all";
  const healthFilter = (table.getColumn("health")?.getFilterValue() as string | undefined) ?? "all";
  const currentPage = table.state.pagination.pageIndex + 1;
  const pageCount = table.getPageCount();
  const filteredCount = table.getFilteredRowModel().rows.length;
  const visibleCount = table.getRowModel().rows.length;

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
          <CardTitle className="leading-none">Active Findings</CardTitle>
          <CardDescription>GPU waste findings across all clusters moving through detection, review, and resolution.</CardDescription>
          <CardAction>
            <div className="flex items-center gap-2">
              <Input
                className="h-7 w-44 md:w-52"
                placeholder="Search findings..."
                value={searchQuery}
                onChange={(e) => { table.setGlobalFilter(e.target.value || undefined); table.setPageIndex(0); }}
              />
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <ListFilter data-icon="inline-start" />Type<ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuRadioGroup
                    value={typeFilter}
                    onValueChange={(v) => { table.getColumn("type")?.setFilterValue(v === "all" ? undefined : v); table.setPageIndex(0); }}
                  >
                    {typeOptions.map((o) => (
                      <DropdownMenuRadioItem key={o} value={o}>{o === "all" ? "All types" : o.replace(/_/g, " ")}</DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm">
                    <ListFilter data-icon="inline-start" />Confidence<ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  <DropdownMenuRadioGroup
                    value={healthFilter}
                    onValueChange={(v) => { table.getColumn("health")?.setFilterValue(v === "all" ? undefined : v); table.setPageIndex(0); }}
                  >
                    {healthOptions.map((o) => (
                      <DropdownMenuRadioItem key={o} value={o}>{o === "all" ? "All confidence" : o}</DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 px-0">
          <div className="overflow-hidden">
            <Table className="**:data-[slot='table-cell']:px-4 **:data-[slot='table-head']:px-4 **:data-[slot='table-cell']:py-4">
              <TableHeader className="border-t **:data-[slot='table-head']:h-11 **:data-[slot='table-head']:font-medium **:data-[slot='table-head']:text-foreground **:data-[slot='table-head']:text-sm">
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id}>
                    {hg.headers.map((h) => (
                      <TableHead key={h.id} colSpan={h.colSpan}>
                        {h.isPlaceholder ? null : <table.FlexRender header={h} />}
                      </TableHead>
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
            <p className="text-muted-foreground text-sm">Viewing {visibleCount} out of {filteredCount.toLocaleString()} findings</p>
            <Pagination className="mx-0 w-auto justify-end">
              <PaginationContent className="gap-1.5">
                <PaginationItem>
                  <PaginationPrevious href="#" className={!table.getCanPreviousPage() ? "pointer-events-none opacity-50" : undefined} onClick={(e) => { preventNav(e); table.previousPage(); }} />
                </PaginationItem>
                {pageNumbers[0] > 1 ? <PaginationItem><PaginationEllipsis /></PaginationItem> : null}
                {pageNumbers.map((n) => (
                  <PaginationItem key={`page-${n}`}>
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
