import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col gap-6">
      {/* MetricCards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border p-4 space-y-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
      {/* RecoveryOverview */}
      <div className="rounded-xl border p-6 space-y-4">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-[240px] w-full" />
      </div>
      {/* FindingsSummary */}
      <div className="rounded-xl border p-6 space-y-4">
        <Skeleton className="h-5 w-36" />
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
