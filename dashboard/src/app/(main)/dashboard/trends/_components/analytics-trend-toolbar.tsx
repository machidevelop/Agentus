"use client";
import * as React from "react";
import { CalendarDays } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const ranges = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
] as const;

export function AnalyticsTrendToolbar() {
  const [range, setRange] = React.useState<string>("30d");
  const selected = ranges.find((r) => r.value === range);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <CalendarDays className="mr-2 size-4" />
          {selected?.label ?? "Select range"}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuRadioGroup value={range} onValueChange={setRange}>
          {ranges.map((r) => (
            <DropdownMenuRadioItem key={r.value} value={r.value}>{r.label}</DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
