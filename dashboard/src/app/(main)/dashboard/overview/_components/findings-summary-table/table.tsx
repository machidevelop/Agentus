"use client";
import * as React from "react";
import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { ChevronFirst, ChevronLast, ListFilter, SortAsc, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { cn } from "@/lib/utils";

import { columns } from "./columns";
import type { FindingSummary } from "./schema";

interface FindingsSummaryTableProps {
  data: FindingSummary[];
}

const PAGE_SIZES = [10, 20, 30] as const;

function getPageNumbers(cur: number, total: number) {
  if (total <= 3) return Array.from({ length: total }, (_, i) => i + 1);
  if (cur <= 2) return [1, 2, 3];
  if (cur >= total - 1) return [total - 2, total - 1, total];
  return [cur - 1, cur, cur + 1];
}

export function FindingsSummaryTable({ data }: FindingsSummaryTableProps) {
  const [rowSelection, setRowSelection] = React.useState({});
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [sorting, setSorting] = React.useState<SortingState>([{ id: "value", desc: true }]);
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const table = useTable({
    features: dataTableFeatures,
    data,
    columns,
    state: { sorting, columnVisibility, rowSelection, columnFilters, pagination },
    getRowId: (row) => row.id,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
  });

  const pageIndex = table.state.pagination.pageIndex;
  const pageCount = Math.max(table.getPageCount(), 1);
  const currentPage = Math.min(pageIndex + 1, pageCount);
  const pageNumbers = getPageNumbers(currentPage, pageCount);

  const typeFilter = table.getColumn("type");
  const selectedTypes = new Set((typeFilter?.getFilterValue() as string[] | undefined) ?? []);

  const verdictFilter = table.getColumn("verdict");
  const selectedVerdicts = new Set((verdictFilter?.getFilterValue() as string[] | undefined) ?? []);

  const confFilter = table.getColumn("confidence");
  const selectedConf = new Set((confFilter?.getFilterValue() as string[] | undefined) ?? []);

  const sortCol = table.state.sorting[0];
  const sortLabel = sortCol ? `${sortCol.id} ${sortCol.desc ? "↓" : "↑"}` : "Value ↓";

  const isFiltered = columnFilters.length > 0;

  function toggleSet(col: ReturnType<typeof table.getColumn>, set: Set<string>, val: string) {
    if (set.has(val)) set.delete(val); else set.add(val);
    col?.setFilterValue(set.size ? Array.from(set) : undefined);
    table.setPageIndex(0);
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 p-4 border-b">
        {/* Type filter */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className={cn("border-dashed", selectedTypes.size > 0 && "border-solid bg-muted")}>
              <ListFilter className="mr-1 size-4" />Type
              {selectedTypes.size > 0 && <Badge variant="secondary" className="ml-1 text-xs">{selectedTypes.size}</Badge>}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44">
            <DropdownMenuLabel>Type</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {["idle_allocation", "queue_inefficiency", "over_allocation", "fragmentation"].map((t) => (
              <DropdownMenuCheckboxItem
                key={t}
                checked={selectedTypes.has(t)}
                onCheckedChange={() => toggleSet(typeFilter, new Set(selectedTypes), t)}
                onSelect={(e) => e.preventDefault()}
              >
                {t.replace(/_/g, " ")}
              </DropdownMenuCheckboxItem>
            ))}
            {selectedTypes.size > 0 && <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => { typeFilter?.setFilterValue(undefined); table.setPageIndex(0); }} className="justify-center">
                <X className="mr-1 size-4" />Clear
              </DropdownMenuItem>
            </>}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Confidence filter */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className={cn("border-dashed", selectedConf.size > 0 && "border-solid bg-muted")}>
              <ListFilter className="mr-1 size-4" />Confidence
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-40">
            {["high", "medium", "low"].map((c) => (
              <DropdownMenuCheckboxItem
                key={c}
                checked={selectedConf.has(c)}
                onCheckedChange={() => toggleSet(confFilter, new Set(selectedConf), c)}
                onSelect={(e) => e.preventDefault()}
              >
                {c}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Verdict filter */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className={cn("border-dashed", selectedVerdicts.size > 0 && "border-solid bg-muted")}>
              <ListFilter className="mr-1 size-4" />Verdict
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44">
            {["LIKELY_VALID", "REVIEW", "INVALID"].map((v) => (
              <DropdownMenuCheckboxItem
                key={v}
                checked={selectedVerdicts.has(v)}
                onCheckedChange={() => toggleSet(verdictFilter, new Set(selectedVerdicts), v)}
                onSelect={(e) => e.preventDefault()}
              >
                {v}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Sort */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              <SortAsc className="mr-1 size-4" />{sortLabel}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44">
            <DropdownMenuRadioGroup value={`${sortCol?.id ?? "value"}:${sortCol?.desc ?? true}`}>
              {[
                { id: "value", desc: true, label: "Value ↓" },
                { id: "value", desc: false, label: "Value ↑" },
                { id: "detected", desc: true, label: "Newest" },
                { id: "detected", desc: false, label: "Oldest" },
              ].map((opt) => (
                <DropdownMenuRadioItem
                  key={`${opt.id}:${opt.desc}`}
                  value={`${opt.id}:${opt.desc}`}
                  onSelect={() => setSorting([{ id: opt.id, desc: opt.desc }])}
                >
                  {opt.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        {isFiltered && (
          <Button variant="ghost" size="sm" onClick={() => { table.resetColumnFilters(); table.setPageIndex(0); }}>
            <X className="mr-1 size-4" />Reset
          </Button>
        )}
      </div>

      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id} className="hover:bg-transparent">
              {hg.headers.map((h) => (
                <TableHead key={h.id} className="h-10 text-muted-foreground text-xs" colSpan={h.colSpan}>
                  {h.isPlaceholder ? null : <table.FlexRender header={h} />}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id} data-state={table.state.rowSelection[row.id] && "selected"} className="hover:bg-muted/20">
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2.5">
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={table.getVisibleLeafColumns().length} className="h-20 text-center text-muted-foreground">
                No findings match filters.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between gap-4 border-t px-4 py-3">
        <span className="text-muted-foreground text-xs">{table.getFilteredRowModel().rows.length} findings</span>
        <Pagination className="mx-0 w-auto">
          <PaginationContent className="gap-1">
            <PaginationItem>
              <PaginationLink
                href="#"
                aria-disabled={!table.getCanPreviousPage()}
                className={cn(!table.getCanPreviousPage() && "pointer-events-none opacity-40")}
                onClick={(e) => { e.preventDefault(); table.setPageIndex(0); }}
              >
                <ChevronFirst className="size-4" />
              </PaginationLink>
            </PaginationItem>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                text="Prev"
                aria-disabled={!table.getCanPreviousPage()}
                className={cn(!table.getCanPreviousPage() && "pointer-events-none opacity-40")}
                onClick={(e) => { e.preventDefault(); table.previousPage(); }}
              />
            </PaginationItem>
            {pageNumbers[0] > 1 && <PaginationItem><PaginationEllipsis /></PaginationItem>}
            {pageNumbers.map((n) => (
              <PaginationItem key={n}>
                <PaginationLink href="#" isActive={pageIndex === n - 1} onClick={(e) => { e.preventDefault(); table.setPageIndex(n - 1); }}>
                  {n}
                </PaginationLink>
              </PaginationItem>
            ))}
            {pageNumbers[pageNumbers.length - 1] < pageCount && <PaginationItem><PaginationEllipsis /></PaginationItem>}
            <PaginationItem>
              <PaginationNext
                href="#"
                aria-disabled={!table.getCanNextPage()}
                className={cn(!table.getCanNextPage() && "pointer-events-none opacity-40")}
                onClick={(e) => { e.preventDefault(); table.nextPage(); }}
              />
            </PaginationItem>
            <PaginationItem>
              <PaginationLink
                href="#"
                aria-disabled={!table.getCanNextPage()}
                className={cn(!table.getCanNextPage() && "pointer-events-none opacity-40")}
                onClick={(e) => { e.preventDefault(); table.setPageIndex(pageCount - 1); }}
              >
                <ChevronLast className="size-4" />
              </PaginationLink>
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </div>
  );
}
