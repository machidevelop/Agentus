import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div data-content-padding="false" className="flex flex-col h-[calc(100vh-3rem)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b bg-background">
        <div className="space-y-1">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-3 w-64" />
        </div>
      </div>
      {/* Canvas area */}
      <div className="flex-1 min-h-0 relative p-6">
        {/* Toolbar skeletons */}
        <div className="absolute top-4 left-4 flex gap-2 z-10">
          <Skeleton className="h-8 w-28 rounded-md" />
          <Skeleton className="h-8 w-28 rounded-md" />
        </div>
        <div className="absolute top-4 right-4 z-10">
          <Skeleton className="h-8 w-20 rounded-md" />
        </div>

        {/* Fake nodes */}
        <div className="flex items-start gap-12 pt-16">
          {/* Trigger */}
          <Skeleton className="h-16 w-36 rounded-xl shrink-0" />
          {/* Coordinator */}
          <Skeleton className="h-32 w-56 rounded-2xl shrink-0" />
          {/* Agent column */}
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-24 w-52 rounded-xl" />
            ))}
          </div>
          {/* Outputs */}
          <div className="flex flex-col gap-3 pt-8">
            <Skeleton className="h-16 w-36 rounded-xl" />
            <Skeleton className="h-16 w-36 rounded-xl" />
          </div>
        </div>

        {/* Bottom status bar */}
        <div className="absolute bottom-4 left-4">
          <Skeleton className="h-7 w-52 rounded-lg" />
        </div>
        {/* Minimap */}
        <div className="absolute bottom-4 right-4">
          <Skeleton className="h-28 w-40 rounded-lg" />
        </div>
      </div>
    </div>
  );
}
