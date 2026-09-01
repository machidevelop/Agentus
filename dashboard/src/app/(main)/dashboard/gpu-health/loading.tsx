import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex min-h-[calc(100svh-var(--dashboard-header-height))] min-w-0 flex-col" data-content-padding="false">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-2 py-2">
        <Skeleton className="h-5 w-32" />
        <div className="flex items-center gap-3">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
      </div>
      <div className="h-px bg-border" />

      {/* GPU grid */}
      <div className="flex-1 p-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
          {Array.from({ length: 32 }).map((_, i) => (
            <Skeleton key={i} className="aspect-square rounded-lg" />
          ))}
        </div>
      </div>

      <div className="h-px bg-border" />
      {/* Footer buttons */}
      <div className="flex flex-wrap gap-2 p-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-11 min-w-32 flex-1 rounded-none" />
        ))}
      </div>
    </div>
  );
}
