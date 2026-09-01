import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div>
        <Skeleton className="h-9 w-56" />
        <Skeleton className="mt-1 h-4 w-80" />
      </div>
      {/* Table header */}
      <div className="rounded-xl border">
        <div className="flex items-center gap-4 border-b px-4 py-3">
          <Skeleton className="h-4 w-8" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-24 ml-auto" />
        </div>
        {/* Rows */}
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 border-b last:border-0 px-4 py-4">
            <Skeleton className="h-4 w-4 rounded" />
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-14" />
            <Skeleton className="h-8 w-20 ml-auto rounded-md" />
          </div>
        ))}
      </div>
    </div>
  );
}
