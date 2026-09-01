import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="space-y-1">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-4 w-80" />
      </div>

      {/* Tab strip + toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-9 w-48" />
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border p-4 space-y-3">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>

      {/* Row 1: chart + realtime */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <div className="rounded-xl border p-6 space-y-4">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-[240px] w-full" />
          </div>
        </div>
        <div className="xl:col-span-5">
          <div className="rounded-xl border p-6 space-y-4">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-[240px] w-full" />
          </div>
        </div>
      </div>

      {/* Row 2: tables */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <div className="rounded-xl border p-6 space-y-3">
            <Skeleton className="h-5 w-28" />
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        </div>
        <div className="xl:col-span-5">
          <div className="rounded-xl border p-6 space-y-3">
            <Skeleton className="h-5 w-32" />
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
