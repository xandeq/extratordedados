export function SkeletonLine({ width = 'w-full', height = 'h-4' }: { width?: string; height?: string }) {
  return <div className={`skeleton ${width} ${height}`} />
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
      <SkeletonLine width="w-1/3" height="h-3" />
      <SkeletonLine width="w-1/2" height="h-7" />
    </div>
  )
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="p-4 border-b border-gray-100">
        <SkeletonLine width="w-1/4" height="h-5" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 p-4 border-b border-gray-50">
          {Array.from({ length: cols }).map((_, j) => (
            <SkeletonLine key={j} width={j === 0 ? 'w-1/3' : 'w-1/6'} height="h-4" />
          ))}
        </div>
      ))}
    </div>
  )
}

export default function LoadingSkeleton() {
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      <SkeletonTable />
    </div>
  )
}
