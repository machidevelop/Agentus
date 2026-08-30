import {
  ArrowUpDown,
  Bell,
  ChevronDown,
  CircleDashed,
  CircleGauge,
  Copy,
  EllipsisVertical,
  FileText,
  RefreshCw,
  Settings,
  SquareTerminal,
  Terminal,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

type GpuStatus = "Active" | "Idle" | "Over-allocated" | "Fragmented";

interface GpuRow {
  gpuName: string;
  status: GpuStatus;
  utilization: number;
  nodeId: string;
  jobId: string | null;
}

interface NodeGroup {
  name: string;
  label: string;
  gpus: GpuRow[];
}

function truncateHash(hash: string) {
  return hash.slice(0, 8) + "…";
}

const nodeGroups: NodeGroup[] = [
  {
    name: "node-group-a",
    label: "Node Group A",
    gpus: [
      { gpuName: "gpu-0", status: "Active", utilization: 78, nodeId: "5082ec7f5d9e62ff", jobId: "7d47fa3f1c0e" },
      { gpuName: "gpu-1", status: "Active", utilization: 82, nodeId: "5082ec7f5d9e62ff", jobId: "7d47fa3f1c0e" },
      { gpuName: "gpu-2", status: "Idle", utilization: 3, nodeId: "5082ec7f5d9e62ff", jobId: null },
      { gpuName: "gpu-3", status: "Over-allocated", utilization: 8, nodeId: "5082ec7f5d9e62ff", jobId: "42a29003bea9" },
      { gpuName: "gpu-4", status: "Active", utilization: 91, nodeId: "2c7d93f76aa51b84", jobId: "90362eef4bba" },
      { gpuName: "gpu-5", status: "Active", utilization: 67, nodeId: "2c7d93f76aa51b84", jobId: "90362eef4bba" },
      { gpuName: "gpu-6", status: "Idle", utilization: 0, nodeId: "2c7d93f76aa51b84", jobId: null },
      { gpuName: "gpu-7", status: "Active", utilization: 55, nodeId: "2c7d93f76aa51b84", jobId: "675b04ccabff" },
    ],
  },
  {
    name: "node-group-b",
    label: "Node Group B",
    gpus: [
      { gpuName: "gpu-0", status: "Active", utilization: 88, nodeId: "b86cd057b7bd21b9", jobId: "6cb3f43b6ca5" },
      { gpuName: "gpu-1", status: "Active", utilization: 73, nodeId: "b86cd057b7bd21b9", jobId: "6cb3f43b6ca5" },
      { gpuName: "gpu-2", status: "Over-allocated", utilization: 5, nodeId: "b86cd057b7bd21b9", jobId: "824986e492a8" },
      { gpuName: "gpu-3", status: "Idle", utilization: 1, nodeId: "b86cd057b7bd21b9", jobId: null },
      { gpuName: "gpu-4", status: "Active", utilization: 61, nodeId: "4857ee28531aaf33", jobId: "504d2a03c507" },
      { gpuName: "gpu-5", status: "Active", utilization: 79, nodeId: "4857ee28531aaf33", jobId: "504d2a03c507" },
      { gpuName: "gpu-6", status: "Fragmented", utilization: 14, nodeId: "4857ee28531aaf33", jobId: "d5c070aef717" },
      { gpuName: "gpu-7", status: "Active", utilization: 84, nodeId: "4857ee28531aaf33", jobId: "d5c070aef717" },
    ],
  },
  {
    name: "node-group-c",
    label: "Node Group C",
    gpus: [
      { gpuName: "gpu-0", status: "Active", utilization: 95, nodeId: "9d63c09285a4b98e", jobId: "d4dabaf99d21" },
      { gpuName: "gpu-1", status: "Active", utilization: 90, nodeId: "9d63c09285a4b98e", jobId: "d4dabaf99d21" },
      { gpuName: "gpu-2", status: "Active", utilization: 71, nodeId: "9d63c09285a4b98e", jobId: "618b9d9187f8" },
      { gpuName: "gpu-3", status: "Idle", utilization: 2, nodeId: "9d63c09285a4b98e", jobId: null },
      { gpuName: "gpu-4", status: "Over-allocated", utilization: 6, nodeId: "5536da2d759c79", jobId: "185b4ed3b04b" },
      { gpuName: "gpu-5", status: "Active", utilization: 66, nodeId: "5536da2d759c79", jobId: "185b4ed3b04b" },
      { gpuName: "gpu-6", status: "Active", utilization: 58, nodeId: "5536da2d759c79", jobId: "29de149a08d3" },
      { gpuName: "gpu-7", status: "Fragmented", utilization: 19, nodeId: "5536da2d759c79", jobId: "29de149a08d3" },
    ],
  },
];

function statusBadge(status: GpuStatus) {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "rounded-sm px-1.5 py-0.5 font-normal",
        status === "Active" && "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
        status === "Idle" && "bg-destructive/10 text-destructive",
        status === "Over-allocated" && "bg-amber-500/10 text-amber-600 dark:text-amber-400",
        status === "Fragmented" && "bg-sky-500/10 text-sky-600 dark:text-sky-400",
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          status === "Active" && "bg-emerald-500",
          status === "Idle" && "bg-destructive",
          status === "Over-allocated" && "bg-amber-500",
          status === "Fragmented" && "bg-sky-500",
        )}
      />
      {status}
    </Badge>
  );
}

function UtilizationMeter({ value }: { value: number }) {
  const isCritical = value >= 85;
  const isLow = value <= 15;

  return (
    <span className="min-w-0 space-y-1">
      <span className="flex items-baseline justify-between gap-2 text-xs">
        <span
          className={cn(
            "font-medium text-emerald-600 tabular-nums dark:text-emerald-400",
            isLow && "text-destructive dark:text-destructive",
            isCritical && "text-amber-600 dark:text-amber-400",
          )}
        >
          {value}%
        </span>
      </span>
      <span className="block h-1.5 w-20 overflow-hidden rounded-full bg-muted-foreground/20">
        <span
          className={cn(
            "block h-full rounded-full bg-emerald-500",
            isLow && "bg-destructive",
            isCritical && "bg-amber-500",
          )}
          style={{ width: `${value}%` }}
        />
      </span>
    </span>
  );
}

function GpuTable({ gpus }: { gpus: GpuRow[] }) {
  return (
    <div className="scrollbar-thin overflow-x-auto [scrollbar-color:var(--border)_transparent]">
      <Table className="**:data-[slot='table-cell']:px-5 **:data-[slot='table-head']:px-5">
        <TableHeader className="bg-muted/50 [&_tr]:border-y">
          <TableRow>
            <TableHead className="font-medium">
              <span className="inline-flex items-center gap-1">
                GPU <ArrowUpDown className="size-4" />
              </span>
            </TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Utilization</TableHead>
            <TableHead>Node ID</TableHead>
            <TableHead>Job ID</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody className="**:data-[slot='table-row']:hover:bg-transparent">
          {gpus.map((gpu) => (
            <TableRow key={`${gpu.nodeId}-${gpu.gpuName}`}>
              <TableCell>
                <span className="flex items-center gap-1.5 font-medium">
                  <CircleGauge className="size-4 text-muted-foreground" />
                  {gpu.gpuName}
                </span>
              </TableCell>
              <TableCell>{statusBadge(gpu.status)}</TableCell>
              <TableCell>
                <UtilizationMeter value={gpu.utilization} />
              </TableCell>
              <TableCell>
                <span className="font-mono text-muted-foreground text-xs">{truncateHash(gpu.nodeId)}</span>
              </TableCell>
              <TableCell>
                {gpu.jobId ? (
                  <span className="font-mono text-xs">{gpu.jobId}</span>
                ) : (
                  <span className="text-muted-foreground text-xs">—</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon-sm" className="-mr-2">
                      <SquareTerminal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent className="w-40" align="end">
                    <DropdownMenuGroup>
                      <DropdownMenuItem>
                        <FileText />
                        View Logs
                      </DropdownMenuItem>
                      <DropdownMenuItem>
                        <Terminal />
                        Open Console
                      </DropdownMenuItem>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                      <DropdownMenuItem>
                        <Copy />
                        Copy GPU ID
                      </DropdownMenuItem>
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function GpuStatusGrid() {
  return (
    <div className="flex flex-col gap-4">
      {nodeGroups.map((group) => (
        <Collapsible
          key={group.name}
          defaultOpen
          className="flex flex-col overflow-hidden rounded-xl border bg-card py-3 text-card-foreground data-[state=open]:gap-3 data-[state=open]:pb-0"
        >
          <div className="flex flex-col gap-2 px-4 sm:flex-row sm:items-center">
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                className="group -ml-2 h-auto w-full justify-start gap-2 px-2 py-1 hover:bg-transparent aria-expanded:bg-transparent sm:flex-1"
              >
                <ChevronDown className="group-data-[state=open]:rotate-180" />
                <div className="flex min-w-0 items-baseline gap-1.5 text-left">
                  <span className="shrink-0 font-medium leading-none">{group.label}</span>
                  <span className="min-w-0 truncate text-muted-foreground text-sm">
                    ({group.gpus.length} GPUs · A100-80GB)
                  </span>
                </div>
              </Button>
            </CollapsibleTrigger>
            <div className="flex w-full items-center justify-between gap-2 sm:ml-auto sm:w-auto sm:justify-end">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon-sm">
                    <EllipsisVertical />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-40" align="end">
                  <DropdownMenuGroup>
                    <DropdownMenuItem>
                      <FileText />
                      Activity Logs
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <Settings />
                      Node Settings
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <RefreshCw />
                      Sync Status
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <Bell />
                      Manage Alerts
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuItem>
                      <Copy />
                      Copy Node Group ID
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          <CollapsibleContent>
            <GpuTable gpus={group.gpus} />
          </CollapsibleContent>
        </Collapsible>
      ))}
    </div>
  );
}
