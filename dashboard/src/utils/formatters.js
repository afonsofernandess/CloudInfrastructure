export function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  if (bytes == null) return '—'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

export function formatDate(isoString) {
  if (!isoString) return '—'
  const date = new Date(isoString)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function vmStateColor(state) {
  if (!state) return 'bg-slate-500/20 text-slate-400'
  const s = state.toUpperCase()
  if (s === 'ACTIVE' || s === 'RUNNING') return 'bg-green-500/20 text-green-400'
  if (s === 'POWEROFF' || s === 'STOPPED') return 'bg-yellow-500/20 text-yellow-400'
  if (s === 'FAILED' || s === 'ERROR') return 'bg-red-500/20 text-red-400'
  return 'bg-slate-500/20 text-slate-400'
}

export function containerStatusColor(status) {
  if (!status) return 'bg-slate-500/20 text-slate-400'
  const s = status.toLowerCase()
  if (s === 'running') return 'bg-green-500/20 text-green-400'
  if (s === 'exited' || s === 'stopped') return 'bg-red-500/20 text-red-400'
  return 'bg-yellow-500/20 text-yellow-400'
}

export function dbStatusColor(status) {
  if (!status) return 'bg-slate-500/20 text-slate-400'
  const s = status.toLowerCase()
  if (s === 'running') return 'bg-green-500/20 text-green-400'
  if (s === 'removed' || s === 'stopped') return 'bg-red-500/20 text-red-400'
  return 'bg-yellow-500/20 text-yellow-400'
}

export function formatTime(date) {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
