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

import { types } from "./data";

interface TypeFilterProps<TData extends RowData> {
  table: ReactTable<DataTableFeatures, TData>;
}

export function TypeFilter<TData extends RowData>({ table }: TypeFilterProps<TData>) {
  const column = table.getColumn("type");
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
          Type
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-52">
        <DropdownMenuGroup>
          {types.map((type) => (
            <DropdownMenuCheckboxItem
              key={type.value}
              checked={selectedValues.has(type.value)}
              onCheckedChange={() => updateFilter(type.value)}
              onSelect={(e) => e.preventDefault()}
            >
              <type.icon className="text-muted-foreground" />
              {type.label}
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
