"use client";
import type { ReactTable, RowData } from "@tanstack/react-table";
import { ListFilter, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

import { confidences } from "./data";

interface ConfidenceFilterProps<TData extends RowData> {
  table: ReactTable<DataTableFeatures, TData>;
}

export function ConfidenceFilter<TData extends RowData>({ table }: ConfidenceFilterProps<TData>) {
  const column = table.getColumn("confidence");
  if (!column) return null;

  const selectedValues = new Set(column.getFilterValue() as string[]);

  function updateFilter(value: string) {
    if (selectedValues.has(value)) selectedValues.delete(value);
    else selectedValues.add(value);
    const filterValues = Array.from(selectedValues);
    column!.setFilterValue(filterValues.length ? filterValues : undefined);
    table.setPageIndex(0);
  }

  function clearFilter() {
    column!.setFilterValue(undefined);
    table.setPageIndex(0);
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className={cn("border-dashed", selectedValues.size > 0 && "border-solid bg-muted text-foreground")}
        >
          <ListFilter data-icon="inline-start" />
          Confidence
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-44">
        <DropdownMenuGroup>
          {confidences.map((conf) => (
            <DropdownMenuCheckboxItem
              key={conf.value}
              checked={selectedValues.has(conf.value)}
              onCheckedChange={() => updateFilter(conf.value)}
              onSelect={(e) => e.preventDefault()}
            >
              <conf.icon className="text-muted-foreground" />
              {conf.label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuGroup>
        {selectedValues.size > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem onSelect={clearFilter} className="justify-center text-center">
                <X />
                Clear filters
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
