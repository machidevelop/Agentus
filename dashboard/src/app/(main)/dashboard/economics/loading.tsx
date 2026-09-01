import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="space-y-1">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>

      {/* Tab strip */}
      <Skeleton className="h-9 w-72" />

      {/* Row 1: KPIs + Cost breakdown */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-6">
          <div className="grid grid-cols-2 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="rounded-xl border p-4 space-y-3">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-8 w-28" />
              </div>
            ))}
          </div>
        </div>
        <div className="xl:col-span-6">
          <div className="rounded-xl border p-6 space-y-4">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-[180px] w-full" />
          </div>
        </div>
      </div>

      {/* Row 2: Chart + Donut */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <div className="rounded-xl border p-6 space-y-4">
            <Skeleton className="h-5 w-36" />
            <Skeleton className="h-[220px] w-full" />
          </div>
        </div>
        <div className="xl:col-span-5">
          <div className="rounded-xl border p-6 space-y-4">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-[220px] w-full" />
          </div>
        </div>
      </div>

      {/* Row 3: 3 cards */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="rounded-xl border p-6 space-y-4">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-[160px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
