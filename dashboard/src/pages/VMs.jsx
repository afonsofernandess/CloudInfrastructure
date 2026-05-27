import { useState } from 'react'
import { Server, Plus, RefreshCw, Trash2, ChevronRight, X, Terminal as TerminalIcon } from 'lucide-react'
import { useVMs, useCreateVM, useDestroyVM } from '../hooks/useVMs'
import { useClusterStatus } from '../hooks/useClusterStatus'
import Modal from '../components/shared/Modal'
import VMTerminal from '../components/VMTerminal'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import EmptyState from '../components/shared/EmptyState'
import SkeletonTable from '../components/shared/SkeletonTable'
import { vmStateColor, formatDate } from '../utils/formatters'
import clsx from 'clsx'

import { 
  ResponsiveContainer, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  Tooltip, 
  CartesianGrid 
} from 'recharts'
import { useVMMetrics } from '../hooks/useMetrics'

function VMMetricsGraph({ vmId }) {
  const { data: metrics, isLoading } = useVMMetrics(vmId)

  if (isLoading || !metrics?.length) {
    return (
      <div className="h-48 flex items-center justify-center bg-slate-800/50 rounded-lg border border-slate-700">
        <span className="text-xs text-slate-500">Loading historical data...</span>
      </div>
    )
  }

  // Format data for chart
  const chartData = metrics.map(m => ({
    time: new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    cpu: m.cpu_usage_pct,
    memory: m.memory_mb
  }))

  return (
    <div className="space-y-6">
      <div>
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">CPU Usage History (%)</h4>
        <div className="h-32 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="time" hide />
              <YAxis hide domain={[0, 100]} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                itemStyle={{ fontSize: '12px' }}
              />
              <Area type="monotone" dataKey="cpu" stroke="#3b82f6" fillOpacity={1} fill="url(#colorCpu)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
      
      <div>
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Memory History (MB)</h4>
        <div className="h-32 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorMem" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="time" hide />
              <YAxis hide domain={['auto', 'auto']} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                itemStyle={{ fontSize: '12px' }}
              />
              <Area type="monotone" dataKey="memory" stroke="#8b5cf6" fillOpacity={1} fill="url(#colorMem)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

function VMDetailDrawer({ vm, onClose }) {
  if (!vm) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-sm bg-slate-900 border-l border-slate-700 h-full overflow-y-auto shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-slate-100">{vm.name || `VM #${vm.id}`}</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-8">
          <div className="grid grid-cols-2 gap-4">
            <Field label="IP Address" value={vm.ip_address || '—'} />
            <div>
              <span className="text-xs text-slate-400 uppercase tracking-wider">State</span>
              <div className="mt-1">
                <span className={clsx('px-2 py-1 text-xs font-medium rounded-full', vmStateColor(vm.state))}>
                  {vm.state === 'SUSPENDED' ? 'Sleeping' : (vm.state || '—')}
                </span>
              </div>
            </div>
            <Field label="CPU Usage" value={vm.cpu_usage_pct != null ? `${vm.cpu_usage_pct.toFixed(1)}%` : '—'} />
            <Field label="Memory (MB)" value={vm.memory_mb ?? '—'} />
            <Field label="Storage" value={vm.disk_gb != null ? `${vm.disk_gb} GB` : '—'} />
          </div>

          <VMMetricsGraph vmId={vm.id} />

          <div className="pt-4 border-t border-slate-800 space-y-3">
             <Field label="Internal ID" value={vm.id} />
             <Field label="OpenNebula ID" value={vm.one_vm_id} />
             <Field label="Created" value={formatDate(vm.created_at)} />
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div>
      <span className="text-xs text-slate-400 uppercase tracking-wider block mb-0.5">{label}</span>
      <span className="text-sm text-slate-100">{value}</span>
    </div>
  )
}

export default function VMs() {
  const { data: vms, isLoading } = useVMs()
  const { data: cluster } = useClusterStatus()
  const createVM = useCreateVM()
  const destroyVM = useDestroyVM()

  const [showLaunchModal, setShowLaunchModal] = useState(false)
  const [selectedVM, setSelectedVM] = useState(null)
  const [terminalVM, setTerminalVM] = useState(null)
  const [confirmDestroyId, setConfirmDestroyId] = useState(null)
  const [launchForm, setLaunchForm] = useState({ 
    template_id: '', 
    name: '',
    cpu: '',
    memory_mb: '',
    disk_gb: '',
    user_data: ''
  })

  const handleLaunch = (e) => {
    e.preventDefault()
    createVM.mutate(
      { 
        template_id: parseInt(launchForm.template_id, 10), 
        name: launchForm.name || undefined,
        cpu: launchForm.cpu ? parseFloat(launchForm.cpu) : undefined,
        memory_mb: launchForm.memory_mb ? parseInt(launchForm.memory_mb, 10) : undefined,
        disk_gb: launchForm.disk_gb ? parseInt(launchForm.disk_gb, 10) : undefined,
        user_data: launchForm.user_data || undefined
      },
      {
        onSuccess: () => {
          setShowLaunchModal(false)
          setLaunchForm({ template_id: '', name: '', cpu: '', memory_mb: '', disk_gb: '', user_data: '' })
        },
      }
    )
  }

  const avgCpu = cluster?.avg_cpu_pct ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Virtual Machines</h1>
          <p className="text-sm text-slate-400 mt-1">Manage your compute instances</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            Auto-refresh 10s
          </div>
          <button
            onClick={() => setShowLaunchModal(true)}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            <Plus className="w-4 h-4" />
            Launch VM
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={4} cols={7} />
          </div>
        ) : !vms?.length ? (
          <EmptyState
            icon={Server}
            title="No virtual machines"
            description="Launch your first VM to get started"
            actionLabel="Launch VM"
            onAction={() => setShowLaunchModal(true)}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-800 text-slate-400 uppercase text-xs tracking-wider">
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">IP Address</th>
                  <th className="px-4 py-3 text-left">ONE ID</th>
                  <th className="px-4 py-3 text-left">State</th>
                  <th className="px-4 py-3 text-left">CPU %</th>
                  <th className="px-4 py-3 text-left">Memory (MB)</th>
                  <th className="px-4 py-3 text-left">Created</th>
                  <th className="px-4 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody>
                {vms.map((vm) => (
                  <tr
                    key={vm.id}
                    className="border-b border-slate-700 hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setSelectedVM(vm)}
                        className="text-slate-100 font-medium hover:text-blue-400 transition-colors flex items-center gap-1"
                      >
                        {vm.name || `VM #${vm.id}`}
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-blue-400">{vm.ip_address || '—'}</td>
                    <td className="px-4 py-3 text-slate-400">{vm.one_vm_id ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className={clsx('px-2 py-1 text-xs font-medium rounded-full', vmStateColor(vm.state))}>
                        {vm.state === 'SUSPENDED' ? 'Sleeping' : (vm.state || '—')}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-300">
                      {vm.cpu_usage_pct != null ? `${vm.cpu_usage_pct.toFixed(1)}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{vm.memory_mb ?? '—'}</td>
                    <td className="px-4 py-3 text-slate-400">{formatDate(vm.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setTerminalVM(vm)}
                          disabled={vm.state !== 'ACTIVE'}
                          className="p-1.5 rounded text-slate-400 hover:bg-blue-500/10 hover:text-blue-400 transition-colors disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
                          title={vm.state === 'ACTIVE' ? 'Open Terminal' : 'VM must be ACTIVE to open terminal'}
                        >
                          <TerminalIcon className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setConfirmDestroyId(vm.id)}
                          className="p-1.5 rounded text-slate-400 hover:bg-red-500/10 hover:text-red-400 transition-colors"
                          title="Destroy VM"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* SLA banner */}
      {cluster && (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">SLA / Cluster Health</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <div className="flex justify-between text-xs text-slate-400 mb-1.5">
                <span>VM Usage</span>
                <span>{cluster.total_vms} / {cluster.max_vms}</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full"
                  style={{ width: `${Math.min(100, (cluster.total_vms / (cluster.max_vms || 1)) * 100)}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs text-slate-400 mb-1.5">
                <span>Avg CPU</span>
                <span>{avgCpu.toFixed(1)}%</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={clsx('h-full rounded-full', avgCpu > 80 ? 'bg-red-500' : avgCpu > 60 ? 'bg-yellow-500' : 'bg-green-500')}
                  style={{ width: `${avgCpu}%` }}
                />
              </div>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-400">Autoscaler:</span>
              <span className={clsx('font-medium', cluster.autoscaler_enabled ? 'text-green-400' : 'text-red-400')}>
                {cluster.autoscaler_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>
        </div>
      )}

      <Modal 
        isOpen={showLaunchModal} 
        onClose={() => { 
          setShowLaunchModal(false); 
          setLaunchForm({ template_id: '', name: '', cpu: '', memory_mb: '', disk_gb: '', user_data: '' }) 
        }} 
        title="Launch Virtual Machine"
      >
        <form onSubmit={handleLaunch} className="space-y-4 max-h-[70vh] overflow-y-auto px-1">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Template ID <span className="text-red-400">*</span></label>
              <input
                type="number"
                value={launchForm.template_id}
                onChange={(e) => setLaunchForm({ ...launchForm, template_id: e.target.value })}
                required
                placeholder="0"
                min="0"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Name</label>
              <input
                type="text"
                value={launchForm.name}
                onChange={(e) => setLaunchForm({ ...launchForm, name: e.target.value })}
                placeholder="my-vm"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">CPU Override</label>
              <input
                type="number"
                step="0.1"
                value={launchForm.cpu}
                onChange={(e) => setLaunchForm({ ...launchForm, cpu: e.target.value })}
                placeholder="0.5"
                min="0.1"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Memory (MB)</label>
              <input
                type="number"
                value={launchForm.memory_mb}
                onChange={(e) => setLaunchForm({ ...launchForm, memory_mb: e.target.value })}
                placeholder="1024"
                min="128"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Storage (GB)</label>
              <input
                type="number"
                value={launchForm.disk_gb}
                onChange={(e) => setLaunchForm({ ...launchForm, disk_gb: e.target.value })}
                placeholder="2"
                min="1"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Startup Script (User Data)</label>
            <textarea
              value={launchForm.user_data}
              onChange={(e) => setLaunchForm({ ...launchForm, user_data: e.target.value })}
              placeholder="#!/bin/sh&#10;apk add python3"
              rows={3}
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full text-xs font-mono"
            />
          </div>

          <div className="flex gap-3 pt-4 sticky bottom-0 bg-slate-900 pb-2">
            <button
              type="button"
              onClick={() => { setShowLaunchModal(false); setLaunchForm({ template_id: '', name: '', cpu: '', memory_mb: '', disk_gb: '', user_data: '' }) }}
              className="flex-1 px-4 py-2 rounded-lg text-sm font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createVM.isPending}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg font-medium transition-colors"
            >
              {createVM.isPending ? 'Launching…' : 'Launch'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Confirm Destroy */}
      <ConfirmDialog
        isOpen={confirmDestroyId != null}
        onClose={() => setConfirmDestroyId(null)}
        onConfirm={() => destroyVM.mutate(confirmDestroyId)}
        title="Destroy VM"
        message="Are you sure you want to destroy this VM? This action cannot be undone."
        confirmLabel="Destroy"
        danger
      />

      {/* VM Detail Drawer */}
      {selectedVM && <VMDetailDrawer vm={selectedVM} onClose={() => setSelectedVM(null)} />}

      {/* VM Terminal */}
      {terminalVM && <VMTerminal ip={terminalVM.ip_address} onClose={() => setTerminalVM(null)} />}
    </div>
  )
}
