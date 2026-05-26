import { useState, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Box, Plus, Play, Square, Trash2, LayoutGrid, List, RefreshCw } from 'lucide-react'
import {
  useContainers,
  useLaunchContainer,
  useStartContainer,
  useStopContainer,
  useRemoveContainer,
} from '../hooks/useContainers'
import { useVMs } from '../hooks/useVMs'
import Modal from '../components/shared/Modal'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import EmptyState from '../components/shared/EmptyState'
import SkeletonTable from '../components/shared/SkeletonTable'
import { containerStatusColor, formatDate } from '../utils/formatters'
import clsx from 'clsx'

const QUICK_IMAGES = ['nginx', 'postgres:16-alpine', 'redis:alpine', 'ubuntu:22.04']

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

function ContainerCard({ container, onStart, onStop, onRemove, vms }) {
  const statusClass = containerStatusColor(container.status)
  const hostingVm = vms?.find((v) => v.id === container.vm_id)
  const vmLabel = hostingVm
    ? `${hostingVm.name || `VM #${hostingVm.id}`} (${hostingVm.ip_address})`
    : `VM ID: ${container.vm_id || '—'}`

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold text-slate-100">{container.name}</div>
          <div className="text-xs text-slate-400 mt-0.5 font-mono">{container.image}</div>
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
      <div className="flex gap-2 mt-auto pt-2 border-t border-slate-700">
        <button
          onClick={() => onStart(container.container_id)}
          disabled={container.status === 'running'}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Play className="w-3.5 h-3.5" /> Start
        </button>
        <button
          onClick={() => onStop(container.container_id)}
          disabled={container.status !== 'running'}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Square className="w-3.5 h-3.5" /> Stop
        </button>
        <button
          onClick={() => onRemove(container.container_id)}
          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
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
        ports: ports.length ? ports : undefined,
        vm_id: selectedVmId ? parseInt(selectedVmId, 10) : undefined
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
                  return (
                    <tr key={c.container_id} className="border-b border-slate-700 hover:bg-slate-800/50 transition-colors">
                      <td className="px-4 py-3 text-slate-100 font-medium">{c.name}</td>
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
                            onClick={() => setConfirmRemoveId(c.container_id)}
                            className="p-1.5 rounded text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Remove"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
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
    </div>
  )
}
