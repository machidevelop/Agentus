import { Ellipsis, FileDown, FileUp, RefreshCw, Share2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function Toolbar() {
  return (
    <div className="flex items-center gap-2">
      <Select defaultValue="all-runs">
        <SelectTrigger className="w-34">
          <SelectValue placeholder="Select run" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="5k-run">5k run</SelectItem>
            <SelectItem value="50k-run">50k run</SelectItem>
            <SelectItem value="all-runs">All runs</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon" variant="outline" aria-label="More actions">
            <Ellipsis />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Validation actions</DropdownMenuLabel>
            <DropdownMenuItem><FileDown />Export report</DropdownMenuItem>
            <DropdownMenuItem><FileUp />Import run data</DropdownMenuItem>
            <DropdownMenuItem><Share2 />Share dashboard</DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem><RefreshCw />Refresh metrics</DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
