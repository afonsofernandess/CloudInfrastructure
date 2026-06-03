import { useState, useEffect, useRef, Fragment } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Box, Plus, Play, Square, Trash2, LayoutGrid, List, RefreshCw, FileText, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  useContainers,
  useLaunchContainer,
  useStartContainer,
  useStopContainer,
  useRemoveContainer,
  useContainerLogs,
  useContainerStats,
} from '../hooks/useContainers'
import { useVMs } from '../hooks/useVMs'
import Modal from '../components/shared/Modal'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import EmptyState from '../components/shared/EmptyState'
import SkeletonTable from '../components/shared/SkeletonTable'
import { containerStatusColor, formatDate } from '../utils/formatters'
import clsx from 'clsx'

const QUICK_IMAGES = ['nginx', 'postgres:16-alpine', 'redis:alpine', 'ubuntu:22.04']

function getScaleGroupInfo(containerName) {
  if (!containerName) return null;
  // Pattern: <username>-<group_name>-worker-<timestamp>-<idx>
  const workerMatch = containerName.match(/^([a-zA-Z0-9]+)-(.+)-worker-\d+-\d+$/);
  if (workerMatch) {
    return { group: workerMatch[2], role: 'worker' };
  }
  // Pattern: <username>-<group_name>-lb
  const lbMatch = containerName.match(/^([a-zA-Z0-9]+)-(.+)-lb$/);
  if (lbMatch) {
    return { group: lbMatch[2], role: 'load_balancer' };
  }
  return null;
}

function formatPorts(ports) {
  if (!ports || typeof ports !== 'object') return '—'
  const entries = Object.entries(ports)
  if (!entries.length) return '—'
  return entries
    .map(([containerPort, bindings]) => {
      if (!bindings?.length) return containerPort
      return bindings.map((b) => `${b.HostPort}→${containerPort}`).join(', ')
    })
    .join(', ')
}

function ContainerCard({ container, onStart, onStop, onRemove, onViewLogs, isExpanded, onToggleExpand, vms }) {
  const statusClass = containerStatusColor(container.status)
  const hostingVm = vms?.find((v) => v.id === container.vm_id)
  const vmLabel = hostingVm
    ? `${hostingVm.name || `VM #${hostingVm.id}`} (${hostingVm.ip_address})`
    : `VM ID: ${container.vm_id || '—'}`

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div>
          <button
            type="button"
            onClick={onToggleExpand}
            className="font-semibold text-slate-100 hover:text-blue-400 transition-colors flex items-center gap-1 text-left"
          >
            {container.name}
            {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
          </button>
          {(() => {
            const scaleInfo = getScaleGroupInfo(container.name);
            if (scaleInfo) {
              return (
                <div className="flex items-center gap-1.5 mt-1">
                  <span className="px-1.5 py-0.5 text-[9px] font-bold rounded bg-blue-500/10 border border-blue-500/20 text-blue-400 uppercase tracking-wider font-sans">
                    Group: {scaleInfo.group}
                  </span>
                  <span className={clsx(
                    "px-1.5 py-0.5 text-[9px] font-bold rounded uppercase tracking-wider border font-sans",
                    scaleInfo.role === 'worker'
                      ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                      : "bg-amber-500/10 border-amber-500/20 text-amber-400"
                  )}>
                    {scaleInfo.role === 'load_balancer' ? 'LB / Nginx' : scaleInfo.role}
                  </span>
                </div>
              );
            }
            return null;
          })()}
          <div className="text-xs text-slate-400 mt-1 font-mono">{container.image}</div>
        </div>
        <span className={clsx('px-2 py-0.5 text-xs font-medium rounded-full', statusClass)}>
          {container.status}
        </span>
      </div>
      <div className="text-xs text-slate-400">
        <span className="font-medium text-slate-300">VM: </span>
        <span className="text-blue-400 font-medium">{vmLabel}</span>
      </div>
      <div className="text-xs text-slate-400">
        <span className="font-medium text-slate-300">Ports: </span>
        {formatPorts(container.ports)}
      </div>
      <div className="text-xs text-slate-500">{formatDate(container.created)}</div>

      {isExpanded && container.status === 'running' && (
        <ContainerStatsPanel containerId={container.container_id} />
      )}
      {isExpanded && container.status !== 'running' && (
        <div className="mt-3 py-2 px-3 bg-slate-950/40 rounded-lg border border-slate-800 text-xs text-slate-500 italic text-center">
          Container is not running.
        </div>
      )}

      <div className="flex gap-2 mt-auto pt-2 border-t border-slate-700">
        <button
          onClick={() => onStart(container.container_id)}
          disabled={container.status === 'running'}
          className="flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Play className="w-3 h-3" /> Start
        </button>
        <button
          onClick={() => onStop(container.container_id)}
          disabled={container.status !== 'running'}
          className="flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Square className="w-3 h-3" /> Stop
        </button>
        <button
          onClick={() => onViewLogs(container)}
          className="flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
        >
          <FileText className="w-3 h-3" /> Logs
        </button>
        <button
          onClick={() => onRemove(container.container_id)}
          className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
    </div>
  )
}

function ContainerLogsModal({ container, onClose }) {
  const [tail, setTail] = useState(100)
  const { data, isLoading, error } = useContainerLogs(container?.container_id, !!container, tail)
  const logEndRef = useRef(null)

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [data?.logs])

  if (!container) return null

  const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

  return (
    <Modal
      isOpen={!!container}
      onClose={onClose}
      title={`Logs: ${container.name}`}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-4">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-300">Image:</span>
            <span className="font-mono text-blue-400 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">{container.image}</span>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1">
              <span>Lines:</span>
              <select
                value={tail}
                onChange={(e) => setTail(parseInt(e.target.value, 10))}
                className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-1.5 py-0.5 focus:outline-none"
              >
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="250">250</option>
                <option value="500">500</option>
              </select>
            </label>
            <div className="flex items-center gap-1.5 text-slate-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              <span>Live Updates</span>
            </div>
          </div>
        </div>

        <div className="bg-black/90 text-slate-200 p-4 rounded-xl border border-slate-800 font-mono text-xs h-96 overflow-y-auto leading-relaxed whitespace-pre-wrap">
          {isLoading && !data ? (
            <div className="flex items-center justify-center h-full text-slate-500">
              <RefreshCw className="w-4 h-4 animate-spin mr-2" />
              Loading logs...
            </div>
          ) : error ? (
            <div className="text-red-400">Error loading logs: {error.message}</div>
          ) : !data?.logs ? (
            <div className="text-slate-500 italic">No log entries found.</div>
          ) : (
            <>
              {data.logs}
              <div ref={logEndRef} />
            </>
          )}
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => {
              if (data?.logs) {
                navigator.clipboard.writeText(data.logs)
                toast.success('Logs copied to clipboard', toastStyle)
              }
            }}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
          >
            Copy Logs
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  )
}

function ContainerStatsPanel({ containerId }) {
  const { data: stats, isLoading, error } = useContainerStats(containerId, true)

  if (isLoading && !stats) {
    return (
      <div className="mt-3 py-3 px-4 bg-slate-950/40 rounded-lg border border-slate-800 text-xs text-slate-500 flex items-center justify-center">
        <RefreshCw className="w-3.5 h-3.5 animate-spin mr-2" />
        Fetching real-time stats...
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-3 py-2 px-3 bg-slate-950/40 rounded-lg border border-slate-800 text-xs text-red-400">
        Failed to fetch stats
      </div>
    )
  }

  const cpu = stats?.cpu_percent ?? 0
  const ram = stats?.memory_mb ?? 0
  const ramLimit = stats?.memory_limit_mb ?? 2048
  const ramPct = stats?.memory_percent ?? 0

  return (
    <div className="mt-3 p-3 bg-slate-950/40 rounded-lg border border-slate-800 space-y-3">
      <div>
        <div className="flex justify-between text-xs text-slate-400 mb-1">
          <span>CPU Usage</span>
          <span className="font-semibold text-slate-300 font-mono">{cpu.toFixed(1)}%</span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all duration-500', cpu > 80 ? 'bg-red-500' : cpu > 50 ? 'bg-yellow-500' : 'bg-blue-500')}
            style={{ width: `${Math.min(100, cpu)}%` }}
          />
        </div>
      </div>

      <div>
        <div className="flex justify-between text-xs text-slate-400 mb-1">
          <span>Memory</span>
          <span className="font-semibold text-slate-300 font-mono">
            {ram.toFixed(1)} MB / {ramLimit.toFixed(0)} MB ({ramPct.toFixed(1)}%)
          </span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all duration-500', ramPct > 80 ? 'bg-red-500' : ramPct > 60 ? 'bg-yellow-500' : 'bg-purple-500')}
            style={{ width: `${Math.min(100, ramPct)}%` }}
          />
        </div>
      </div>
    </div>
  )
}

export default function Containers() {
  const { data: containers, isLoading } = useContainers()
  const { data: vms } = useVMs()
  const launch = useLaunchContainer()
  const start = useStartContainer()
  const stop = useStopContainer()
  const remove = useRemoveContainer()

  const [viewMode, setViewMode] = useState('grid')
  const [showLaunchModal, setShowLaunchModal] = useState(false)
  const [confirmRemoveId, setConfirmRemoveId] = useState(null)
  const [selectedLogsContainer, setSelectedLogsContainer] = useState(null)
  const [expandedContainerId, setExpandedContainerId] = useState(null)
  const queryClient = useQueryClient()

  // Time-based stepper: track when launch started and auto-advance stages
  const launchStartRef = useRef(null)
  const [elapsedSecs, setElapsedSecs] = useState(0)

  useEffect(() => {
    if (launch.isPending) {
      if (!launchStartRef.current) {
        launchStartRef.current = Date.now()
        setElapsedSecs(0)
      }
      const iv = setInterval(() => {
        setElapsedSecs(Math.floor((Date.now() - launchStartRef.current) / 1000))
        queryClient.invalidateQueries({ queryKey: ['vms'] })
      }, 1000)
      return () => clearInterval(iv)
    } else {
      launchStartRef.current = null
      setElapsedSecs(0)
    }
  }, [launch.isPending, queryClient])

  const getLaunchProgress = () => {
    const hasActiveVM = vms?.some(v => v.state === 'ACTIVE')
    const hasSuspendedVM = vms?.some(v => ['SUSPENDED', 'POWEROFF', 'STOPPED'].includes(v.state))

    // Determine which scenario we're in based on selected VM
    let scenario = 'new'  // provisioning from scratch
    if (selectedVmId) {
      const target = vms?.find(v => v.id === parseInt(selectedVmId, 10))
      if (target?.state === 'ACTIVE') scenario = 'active'
      else if (['SUSPENDED', 'POWEROFF', 'STOPPED'].includes(target?.state)) scenario = 'sleeping'
    } else if (hasActiveVM) {
      scenario = 'active'
    } else if (hasSuspendedVM) {
      scenario = 'sleeping'
    }

    // Time thresholds for stage transitions (seconds)
    // active:   0s→connecting,  10s→deploying
    // sleeping: 0s→waking,      20s→connecting,  35s→deploying
    // new:      0s→booting,     35s→docker,       50s→deploying
    let stages, step, message

    if (scenario === 'active') {
      const s1 = elapsedSecs < 10
      const s2 = elapsedSecs >= 10 && elapsedSecs < 20
      const s3 = elapsedSecs >= 20
      stages = [
        { name: 'Verifying VM is running', status: s1 ? 'current' : 'complete' },
        { name: 'Connecting to Docker daemon', status: s1 ? 'upcoming' : s2 ? 'current' : 'complete' },
        { name: 'Pulling image & deploying container', status: s3 ? 'current' : 'upcoming' },
      ]
      message = s1 ? 'Verifying VM status...' : s2 ? 'Connecting to Docker daemon...' : 'Pulling image & launching container...'
    } else if (scenario === 'sleeping') {
      const s1 = elapsedSecs < 20
      const s2 = elapsedSecs >= 20 && elapsedSecs < 35
      const s3 = elapsedSecs >= 35
      stages = [
        { name: 'Waking up sleeping VM (~20s)', status: s1 ? 'current' : 'complete' },
        { name: 'Connecting to Docker daemon', status: s1 ? 'upcoming' : s2 ? 'current' : 'complete' },
        { name: 'Pulling image & deploying container', status: s3 ? 'current' : 'upcoming' },
      ]
      message = s1 ? `Resuming VM... (${elapsedSecs}s)` : s2 ? 'Connecting to Docker...' : 'Pulling image & starting container...'
    } else {
      // new VM provisioning
      const s1 = elapsedSecs < 35
      const s2 = elapsedSecs >= 35 && elapsedSecs < 55
      const s3 = elapsedSecs >= 55
      stages = [
        { name: 'Allocating & booting new VM (~35s)', status: s1 ? 'current' : 'complete' },
        { name: 'Installing Docker & verifying socket', status: s1 ? 'upcoming' : s2 ? 'current' : 'complete' },
        { name: 'Pulling image & deploying container', status: s3 ? 'current' : 'upcoming' },
      ]
      message = s1 ? `Provisioning VM from scratch... (${elapsedSecs}s)` : s2 ? 'Installing Docker on new VM...' : 'Pulling image & launching container...'
    }

    return { stages, message }
  }

  const [image, setImage] = useState('')
  const [name, setName] = useState('')
  const [envRows, setEnvRows] = useState([{ key: '', value: '' }])
  const [portsInput, setPortsInput] = useState('')
  const [selectedVmId, setSelectedVmId] = useState('')
  const [isScaleGroup, setIsScaleGroup] = useState(false)
  const [replicas, setReplicas] = useState(1)
  const [containerPort, setContainerPort] = useState('80/tcp')

  const activeVms = vms?.filter((vm) => ['ACTIVE', 'SUSPENDED', 'POWEROFF', 'STOPPED', 'PENDING'].includes(vm.state)) || []

  // Auto-select VM if there is exactly one active
  useEffect(() => {
    if (activeVms.length === 1 && !selectedVmId) {
      setSelectedVmId(activeVms[0].id.toString())
    }
  }, [activeVms, selectedVmId])

  const resetForm = () => {
    setImage('')
    setName('')
    setEnvRows([{ key: '', value: '' }])
    setPortsInput('')
    setSelectedVmId(activeVms.length === 1 ? activeVms[0].id.toString() : '')
    setIsScaleGroup(false)
    setReplicas(1)
    setContainerPort('80/tcp')
  }

  const handleLaunch = (e) => {
    e.preventDefault()
    const env = {}
    envRows.forEach(({ key, value }) => { if (key) env[key] = value })
    const ports = portsInput
      ? portsInput.split(',').map((p) => p.trim()).filter(Boolean)
      : []
    launch.mutate(
      {
        image,
        name: name || undefined,
        env,
        ports: !isScaleGroup && ports.length ? ports : undefined,
        vm_id: !isScaleGroup && selectedVmId ? parseInt(selectedVmId, 10) : undefined,
        is_scale_group: isScaleGroup,
        replicas: isScaleGroup ? parseInt(replicas, 10) : undefined,
        container_port: isScaleGroup ? containerPort : undefined
      },
      {
        onSuccess: () => {
          setShowLaunchModal(false)
          resetForm()
        },
      }
    )
  }

  const addEnvRow = () => setEnvRows([...envRows, { key: '', value: '' }])
  const removeEnvRow = (i) => setEnvRows(envRows.filter((_, idx) => idx !== i))
  const updateEnvRow = (i, field, val) => {
    const next = [...envRows]
    next[i] = { ...next[i], [field]: val }
    setEnvRows(next)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Containers</h1>
          <p className="text-sm text-slate-400 mt-1">Manage your Docker containers</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            Auto-refresh 10s
          </div>
          {/* View toggle */}
          <div className="flex items-center bg-slate-800 border border-slate-700 rounded-lg p-1">
            <button
              onClick={() => setViewMode('grid')}
              className={clsx('p-1.5 rounded transition-colors', viewMode === 'grid' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-100')}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={clsx('p-1.5 rounded transition-colors', viewMode === 'list' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-100')}
            >
              <List className="w-4 h-4" />
            </button>
          </div>
          <button
            onClick={() => setShowLaunchModal(true)}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            New Container
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
          <SkeletonTable rows={4} cols={6} />
        </div>
      ) : !containers?.length ? (
        <div className="bg-slate-900 border border-slate-700 rounded-xl">
          <EmptyState
            icon={Box}
            title="No containers"
            description="Launch a container to get started"
            actionLabel="New Container"
            onAction={() => setShowLaunchModal(true)}
          />
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {containers.map((c) => (
            <ContainerCard
              key={c.container_id}
              container={c}
              vms={vms}
              onStart={(id) => start.mutate(id)}
              onStop={(id) => stop.mutate(id)}
              onRemove={(id) => setConfirmRemoveId(id)}
              onViewLogs={(c) => setSelectedLogsContainer(c)}
              isExpanded={expandedContainerId === c.container_id}
              onToggleExpand={() => setExpandedContainerId(expandedContainerId === c.container_id ? null : c.container_id)}
            />
          ))}
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-800 text-slate-400 uppercase text-xs tracking-wider">
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">Image</th>
                  <th className="px-4 py-3 text-left">Host VM</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Ports</th>
                  <th className="px-4 py-3 text-left">Created</th>
                  <th className="px-4 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody>
                {containers.map((c) => {
                  const hostingVm = vms?.find((v) => v.id === c.vm_id)
                  const vmLabel = hostingVm
                    ? `${hostingVm.name || `VM #${hostingVm.id}`} (${hostingVm.ip_address})`
                    : `VM #${c.vm_id || '—'}`
                  const isExpanded = expandedContainerId === c.container_id
                  return (
                    <Fragment key={c.container_id}>
                      <tr className="border-b border-slate-700 hover:bg-slate-800/50 transition-colors">
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            onClick={() => setExpandedContainerId(isExpanded ? null : c.container_id)}
                            className="text-slate-100 font-medium hover:text-blue-400 transition-colors flex items-center gap-1 text-left font-outfit"
                          >
                            {c.name}
                            {isExpanded ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />}
                          </button>
                        </td>
                        <td className="px-4 py-3 text-slate-400 font-mono text-xs">{c.image}</td>
                        <td className="px-4 py-3 text-blue-400 text-xs font-semibold">{vmLabel}</td>
                        <td className="px-4 py-3">
                          <span className={clsx('px-2 py-1 text-xs font-medium rounded-full', containerStatusColor(c.status))}>
                            {c.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{formatPorts(c.ports)}</td>
                        <td className="px-4 py-3 text-slate-400">{formatDate(c.created)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => start.mutate(c.container_id)}
                              disabled={c.status === 'running'}
                              className="p-1.5 rounded text-green-400 hover:bg-green-500/10 disabled:opacity-40 transition-colors"
                              title="Start"
                            >
                              <Play className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => stop.mutate(c.container_id)}
                              disabled={c.status !== 'running'}
                              className="p-1.5 rounded text-yellow-400 hover:bg-yellow-500/10 disabled:opacity-40 transition-colors"
                              title="Stop"
                            >
                              <Square className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => setSelectedLogsContainer(c)}
                              className="p-1.5 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition-colors"
                              title="View Logs"
                            >
                              <FileText className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => setConfirmRemoveId(c.container_id)}
                              className="p-1.5 rounded text-red-400 hover:bg-red-500/10 transition-colors"
                              title="Remove"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-900/30 border-b border-slate-700">
                          <td colSpan={7} className="px-6 py-3">
                            <div className="max-w-md">
                              {c.status === 'running' ? (
                                <ContainerStatsPanel containerId={c.container_id} />
                              ) : (
                                <div className="py-2 px-3 bg-slate-950/40 rounded-lg border border-slate-800 text-xs text-slate-500 italic text-center">
                                  Container is not running.
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Launch Modal */}
      <Modal
        isOpen={showLaunchModal}
        onClose={() => { if (!launch.isPending) { setShowLaunchModal(false); resetForm() } }}
        title={launch.isPending ? "Deploying Container..." : "Launch Container"}
        maxWidth={launch.isPending ? "max-w-md" : "max-w-xl"}
      >
        {launch.isPending ? (
          <div className="py-6 px-4 flex flex-col items-center justify-center text-center">
            {/* Animated Spinner Icon */}
            <div className="relative flex items-center justify-center mb-6">
              <div className="w-16 h-16 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin"></div>
              <Box className="w-6 h-6 text-blue-400 absolute animate-pulse" />
            </div>

            <h3 className="text-lg font-semibold text-slate-100 mb-2 font-outfit">Deploying Container</h3>
            <p className="text-xs text-slate-400 max-w-sm mb-6 leading-relaxed">
              {getLaunchProgress().message}
            </p>

            {/* Stepper */}
            <div className="w-full text-left space-y-4 bg-slate-900/60 border border-slate-800/80 rounded-xl p-4">
              {getLaunchProgress().stages.map((stage, idx) => (
                <div key={idx} className="flex items-center gap-3">
                  <div className="flex items-center justify-center">
                    {stage.status === 'complete' ? (
                      <div className="w-5 h-5 rounded-full bg-green-500/20 border border-green-500 flex items-center justify-center text-[10px] text-green-400 font-bold">
                        ✓
                      </div>
                    ) : stage.status === 'current' ? (
                      <div className="w-5 h-5 rounded-full bg-blue-500/20 border border-blue-500 flex items-center justify-center">
                        <div className="w-2 h-2 rounded-full bg-blue-400 animate-ping"></div>
                      </div>
                    ) : (
                      <div className="w-5 h-5 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-[10px] text-slate-500">
                        {idx + 1}
                      </div>
                    )}
                  </div>
                  <span className={clsx(
                    'text-xs font-medium',
                    stage.status === 'complete' ? 'text-slate-300 line-through opacity-60' :
                    stage.status === 'current' ? 'text-blue-400 font-semibold' : 'text-slate-500'
                  )}>
                    {stage.name}
                  </span>
                </div>
              ))}
            </div>

            <div className="mt-6 flex items-center gap-2 text-[10px] text-blue-400 bg-blue-500/5 border border-blue-500/10 px-3 py-1.5 rounded-lg">
              <span>ℹ️</span> 
              <span>First-time setup takes ~45s to configure the VM. Subsequent runs are near-instant!</span>
            </div>
          </div>
        ) : (
          <form onSubmit={handleLaunch} className="space-y-4">
            {!isScaleGroup && (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5 font-outfit">Target Virtual Machine</label>
                <select
                  value={selectedVmId}
                  onChange={(e) => setSelectedVmId(e.target.value)}
                  className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
                >
                  <option value="">Auto-select / Provision VM (Recommended)</option>
                  {activeVms.map((vm) => {
                    const stateLabel = vm.state === 'SUSPENDED' ? 'Sleeping' : vm.state;
                    const ipLabel = vm.ip_address && vm.ip_address !== '—' ? vm.ip_address : 'No IP';
                    return (
                      <option key={vm.id} value={vm.id}>
                        {vm.name || `VM #${vm.id}`} ({ipLabel} - {stateLabel})
                      </option>
                    );
                  })}
                </select>
                {selectedVmId ? (() => {
                  const target = vms?.find(v => v.id === parseInt(selectedVmId, 10));
                  if (target && (target.state === 'SUSPENDED' || target.state === 'POWEROFF' || target.state === 'STOPPED')) {
                    return (
                      <div className="mt-2 text-xs text-purple-400 bg-purple-500/5 border border-purple-500/10 px-3 py-2 rounded-lg flex items-start gap-2">
                        <span className="mt-0.5">🌙</span>
                        <span>This VM is sleeping. Launching the container will automatically wake it up (~30s).</span>
                      </div>
                    );
                  }
                  return null;
                })() : (
                  <div className="mt-2 text-xs text-blue-400 bg-blue-500/5 border border-blue-500/10 px-3 py-2 rounded-lg flex items-start gap-2">
                    <span className="mt-0.5">💡</span>
                    <span>If no running VM is found, a new VM will be automatically provisioned and configured (~45s).</span>
                  </div>
                )}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5 font-outfit">Image <span className="text-red-400">*</span></label>
              <input
                type="text"
                value={image}
                onChange={(e) => setImage(e.target.value)}
                required
                placeholder="nginx:latest"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
              <div className="flex flex-wrap gap-2 mt-2">
                {QUICK_IMAGES.map((img) => (
                  <button
                    key={img}
                    type="button"
                    onClick={() => setImage(img)}
                    className="px-2 py-1 text-xs rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors font-mono"
                  >
                    {img}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5 font-outfit">Name <span className="text-slate-500">(optional)</span></label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-container"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5 font-outfit">
                <label className="block text-sm font-medium text-slate-300">Environment Variables</label>
                <button type="button" onClick={addEnvRow} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                  + Add row
                </button>
              </div>
            <div className="space-y-2">
              {envRows.map((row, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    type="text"
                    value={row.key}
                    onChange={(e) => updateEnvRow(i, 'key', e.target.value)}
                    placeholder="KEY"
                    className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none flex-1 text-xs font-mono"
                  />
                  <input
                    type="text"
                    value={row.value}
                    onChange={(e) => updateEnvRow(i, 'value', e.target.value)}
                    placeholder="value"
                    className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none flex-1 text-xs font-mono"
                  />
                  {envRows.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeEnvRow(i)}
                      className="px-2 text-slate-400 hover:text-red-400 transition-colors"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2 py-1">
            <input
              type="checkbox"
              id="is_scale_group"
              checked={isScaleGroup}
              onChange={(e) => setIsScaleGroup(e.target.checked)}
              className="w-4 h-4 rounded text-blue-600 bg-slate-800 border-slate-600 focus:ring-blue-500 focus:ring-2"
            />
            <label htmlFor="is_scale_group" className="text-sm font-medium text-slate-300 cursor-pointer select-none">
              Enable Load Balancing & Scaling (Container Scale Group)
            </label>
          </div>

          {isScaleGroup && (
            <div className="bg-slate-800/40 border border-slate-700/60 rounded-lg p-3 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                    Replicas Count
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={replicas}
                    onChange={(e) => setReplicas(parseInt(e.target.value, 10) || 1)}
                    className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                    Container Port
                  </label>
                  <input
                    type="text"
                    value={containerPort}
                    onChange={(e) => setContainerPort(e.target.value)}
                    placeholder="80/tcp"
                    className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full text-xs font-mono"
                  />
                </div>
              </div>
              <span className="text-[10px] text-slate-500 block">
                Deploy workers load balanced under a single Nginx reverse proxy endpoint.
              </span>
            </div>
          )}

          {!isScaleGroup && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Ports <span className="text-slate-500">(e.g. 80/tcp,443/tcp)</span></label>
              <input
                type="text"
                value={portsInput}
                onChange={(e) => setPortsInput(e.target.value)}
                placeholder="80/tcp,443/tcp"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full font-mono text-sm"
              />
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={() => { setShowLaunchModal(false); resetForm() }}
              className="flex-1 px-4 py-2 rounded-lg text-sm font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={launch.isPending}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg font-medium transition-colors"
            >
              {launch.isPending ? 'Launching…' : 'Launch'}
            </button>
          </div>
        </form>
      )}
    </Modal>

      <ConfirmDialog
        isOpen={confirmRemoveId != null}
        onClose={() => setConfirmRemoveId(null)}
        onConfirm={() => remove.mutate(confirmRemoveId)}
        title="Remove Container"
        message="This will permanently remove the container. Continue?"
        confirmLabel="Remove"
        danger
      />

      <ContainerLogsModal
        container={selectedLogsContainer}
        onClose={() => setSelectedLogsContainer(null)}
      />
    </div>
  )
}
