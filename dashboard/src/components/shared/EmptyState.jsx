export default function EmptyState({ icon: Icon, title, description, actionLabel, onAction }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      {Icon && (
        <div className="mb-4 p-4 rounded-full bg-slate-800">
          <Icon className="w-12 h-12 text-slate-500" />
        </div>
      )}
      <h3 className="text-lg font-semibold text-slate-300 mb-2">{title}</h3>
      {description && <p className="text-slate-500 text-sm max-w-sm mb-6">{description}</p>}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium transition-colors focus:ring-2 focus:ring-blue-500 focus:outline-none"
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}
