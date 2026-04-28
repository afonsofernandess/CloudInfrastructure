export default function SkeletonTable({ rows = 5, cols = 4 }) {
  return (
    <div className="w-full">
      <div className="grid gap-3 px-4 py-3 bg-slate-800 rounded-t-lg" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="h-3 bg-slate-700 rounded animate-pulse" />
        ))}
      </div>
      <div className="divide-y divide-slate-700 border border-slate-700 border-t-0 rounded-b-lg overflow-hidden">
        {Array.from({ length: rows }).map((_, rowIdx) => (
          <div
            key={rowIdx}
            className="grid gap-3 px-4 py-4"
            style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
          >
            {Array.from({ length: cols }).map((_, colIdx) => (
              <div
                key={colIdx}
                className="h-4 bg-slate-700 dark:bg-slate-700 rounded animate-pulse"
                style={{ width: colIdx === 0 ? '60%' : colIdx === cols - 1 ? '40%' : '80%' }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
