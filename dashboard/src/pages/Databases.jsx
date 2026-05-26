import { useState, useEffect } from 'react'
import { Database, Plus, Key, Trash2, Eye, EyeOff, Copy, Check, Activity } from 'lucide-react'
import { useDatabases, useProvisionDB, useDeprovisionDB } from '../hooks/useDatabases'
import { useVMs } from '../hooks/useVMs'
import Modal from '../components/shared/Modal'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import EmptyState from '../components/shared/EmptyState'
import SkeletonTable from '../components/shared/SkeletonTable'
import { dbStatusColor, formatDate } from '../utils/formatters'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import client from '../api/client'
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid
} from 'recharts'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

function parseSizeToMB(sizeStr) {
  if (!sizeStr) return 0
  const match = sizeStr.trim().match(/^([0-9.]+)\s*([a-zA-Z]+)$/)
  if (!match) return 0
  const value = parseFloat(match[1])
  const unit = match[2].toLowerCase()
  if (unit === 'bytes' || unit === 'b') return value / (1024 * 1024)
  if (unit === 'kb') return value / 1024
  if (unit === 'mb') return value
  if (unit === 'gb') return value * 1024
  return value
}

function CredentialsModal({ db, onClose }) {
  const [showPassword, setShowPassword] = useState(false)
  const [copied, setCopied] = useState(false)
  const [metricsHistory, setMetricsHistory] = useState([])
  const creds = db?.credentials

  useEffect(() => {
    if (!db) return
    setMetricsHistory([])

    const fetchMetrics = async () => {
      try {
        const res = await client.get(`/databases/${db.id}/metrics`)
        setMetricsHistory((prev) => {
          const next = [...prev, {
            time: new Date(res.data.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            connections: res.data.active_connections,
            sizeMB: parseSizeToMB(res.data.db_size),
            sizeRaw: res.data.db_size
          }]
          if (next.length > 15) next.shift()
          return next
        })
      } catch (err) {
        console.error(err)
      }
    }

    fetchMetrics()
    const interval = setInterval(fetchMetrics, 5000)
    return () => clearInterval(interval)
  }, [db])

  const copyConnectionString = async () => {
    if (!creds?.connection_string) return
    await navigator.clipboard.writeText(creds.connection_string)
    setCopied(true)
    toast.success('Copied to clipboard', toastStyle)
    setTimeout(() => setCopied(false), 2000)
  }

  const latestMetrics = metricsHistory[metricsHistory.length - 1]

  return (
    <Modal isOpen={!!db} onClose={onClose} title="Database Details & Metrics" maxWidth="max-w-4xl">
      {creds && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left Column: Credentials */}
          <div className="space-y-4 flex flex-col justify-between">
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-300 border-b border-slate-700 pb-2">Credentials</h3>
              <div className="grid grid-cols-2 gap-4">
                <CredField label="Host" value={creds.host} />
                <CredField label="Port" value={creds.port} />
                <CredField label="Database" value={creds.db_name} />
                <CredField label="User" value={creds.db_user} />
              </div>
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wider block mb-1">Password</span>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    readOnly
                    value={creds.db_password || ''}
                    className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 pr-10 text-slate-100 w-full text-sm font-mono focus:outline-none"
                  />
                  <button
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              <div>
                <span className="text-xs text-slate-400 uppercase tracking-wider block mb-1">Connection String</span>
                <div className="relative">
                  <input
                    type="text"
                    readOnly
                    value={creds.connection_string || ''}
                    className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 pr-10 text-slate-100 w-full text-xs font-mono focus:outline-none"
                  />
                  <button
                    onClick={copyConnectionString}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors"
                    title="Copy"
                  >
                    {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-full px-4 py-2 rounded-lg text-sm font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors mt-4"
            >
              Close
            </button>
          </div>

          {/* Right Column: Live Metrics */}
          <div className="space-y-4 border-t lg:border-t-0 lg:border-l border-slate-700 pt-4 lg:pt-0 lg:pl-6">
            <h3 className="text-sm font-semibold text-slate-300 border-b border-slate-700 pb-2 flex items-center gap-1.5">
              <Activity className="w-4 h-4 text-blue-400" /> Live Performance Metrics
            </h3>
            {metricsHistory.length === 0 ? (
              <div className="h-64 flex items-center justify-center bg-slate-800/20 rounded-lg border border-slate-700/50">
                <span className="text-xs text-slate-500">Connecting and fetching real-time metrics...</span>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Stats Row */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-3">
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">Connections</span>
                    <span className="text-xl font-bold text-slate-100">{latestMetrics?.connections ?? 0}</span>
                  </div>
                  <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-3">
                    <span className="text-xs text-slate-400 uppercase tracking-wider block">Database Size</span>
                    <span className="text-xl font-bold text-slate-100">{latestMetrics?.sizeRaw ?? '—'}</span>
                  </div>
                </div>

                {/* Connections Graph */}
                <div>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Active Connections (5s intervals)</h4>
                  <div className="h-28 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={metricsHistory}>
                        <defs>
                          <linearGradient id="colorConnections" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="time" hide />
                        <YAxis hide domain={[0, 'auto']} />
                        <Tooltip 
                          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                          itemStyle={{ fontSize: '11px' }}
                        />
                        <Area type="monotone" dataKey="connections" stroke="#3b82f6" fillOpacity={1} fill="url(#colorConnections)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Size Graph */}
                <div>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Database Size over time (MB)</h4>
                  <div className="h-28 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={metricsHistory}>
                        <defs>
                          <linearGradient id="colorSize" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="time" hide />
                        <YAxis hide domain={['auto', 'auto']} />
                        <Tooltip 
                          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                          itemStyle={{ fontSize: '11px' }}
                        />
                        <Area type="monotone" dataKey="sizeMB" stroke="#10b981" fillOpacity={1} fill="url(#colorSize)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

function CredField({ label, value }) {
  return (
    <div>
      <span className="text-xs text-slate-400 uppercase tracking-wider block mb-1">{label}</span>
      <span className="text-sm text-slate-100 font-mono">{value ?? '—'}</span>
    </div>
  )
}

export default function Databases() {
  const { data: databases, isLoading } = useDatabases()
  const { data: vms } = useVMs()
  const provision = useProvisionDB()
  const deprovision = useDeprovisionDB()

  const [showProvisionModal, setShowProvisionModal] = useState(false)
  const [credentialsDB, setCredentialsDB] = useState(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [form, setForm] = useState({ name: '', db_name: '' })
  const [selectedVmId, setSelectedVmId] = useState('')

  const activeVms = vms?.filter((vm) => ['ACTIVE', 'SUSPENDED', 'POWEROFF', 'STOPPED', 'PENDING'].includes(vm.state)) || []

  // Auto-select VM if there is exactly one active
  useEffect(() => {
    if (activeVms.length === 1 && !selectedVmId) {
      setSelectedVmId(activeVms[0].id.toString())
    }
  }, [activeVms, selectedVmId])

  const handleProvision = (e) => {
    e.preventDefault()
    provision.mutate(
      {
        name: form.name,
        db_name: form.db_name || undefined,
        vm_id: selectedVmId ? parseInt(selectedVmId, 10) : undefined
      },
      {
        onSuccess: () => {
          setShowProvisionModal(false)
          setForm({ name: '', db_name: '' })
          setSelectedVmId(activeVms.length === 1 ? activeVms[0].id.toString() : '')
        },
      }
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Databases</h1>
          <p className="text-sm text-slate-400 mt-1">Manage your PostgreSQL instances</p>
        </div>
        <button
          onClick={() => setShowProvisionModal(true)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          Provision DB
        </button>
      </div>

      {/* Table */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={4} cols={7} />
          </div>
        ) : !databases?.length ? (
          <EmptyState
            icon={Database}
            title="No databases"
            description="Provision your first PostgreSQL instance"
            actionLabel="Provision DB"
            onAction={() => setShowProvisionModal(true)}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-800 text-slate-400 uppercase text-xs tracking-wider">
                  <th className="px-4 py-3 text-left">Instance Name</th>
                  <th className="px-4 py-3 text-left">Container ID</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Host VM</th>
                  <th className="px-4 py-3 text-left">Port</th>
                  <th className="px-4 py-3 text-left">DB Name</th>
                  <th className="px-4 py-3 text-left">Created</th>
                  <th className="px-4 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody>
                {databases.map((db) => {
                  const hostingVm = vms?.find((v) => v.id === db.vm_id)
                  const vmLabel = hostingVm
                    ? `${hostingVm.name || `VM #${hostingVm.id}`} (${hostingVm.ip_address})`
                    : db.credentials?.host || '—'
                  return (
                    <tr key={db.id} className="border-b border-slate-700 hover:bg-slate-800/50 transition-colors">
                      <td className="px-4 py-3 text-slate-100 font-medium">{db.instance_name}</td>
                      <td className="px-4 py-3 text-slate-400 font-mono text-xs">
                        {db.container_id ? db.container_id.slice(0, 12) : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <span className={clsx('px-2 py-1 text-xs font-medium rounded-full', dbStatusColor(db.status))}>
                          {db.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-blue-400 text-xs font-semibold">{vmLabel}</td>
                      <td className="px-4 py-3 text-slate-400">{db.credentials?.port ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-400">{db.credentials?.db_name ?? '—'}</td>
                      <td className="px-4 py-3 text-slate-400">{formatDate(db.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setCredentialsDB(db)}
                          className="p-1.5 rounded text-blue-400 hover:bg-blue-500/10 transition-colors"
                          title="Credentials"
                        >
                          <Key className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(db.id)}
                          className="p-1.5 rounded text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Provision Modal */}
      <Modal
        isOpen={showProvisionModal}
        onClose={() => {
          setShowProvisionModal(false)
          setForm({ name: '', db_name: '' })
          setSelectedVmId(activeVms.length === 1 ? activeVms[0].id.toString() : '')
        }}
        title="Provision Database"
      >
        <form onSubmit={handleProvision} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Target Virtual Machine</label>
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
            {activeVms.length === 0 && (
              <p className="text-xs text-blue-400 mt-1.5 flex items-center gap-1">
                <span>ℹ️</span> No active VMs found. The platform will automatically wake up or provision a VM for you in the background!
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Instance Name <span className="text-red-400">*</span></label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              placeholder="my-database"
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">DB Name <span className="text-slate-500">(optional)</span></label>
            <input
              type="text"
              value={form.db_name}
              onChange={(e) => setForm({ ...form, db_name: e.target.value })}
              placeholder="Defaults to your username"
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full placeholder-slate-500"
            />
          </div>
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={() => { setShowProvisionModal(false); setForm({ name: '', db_name: '' }) }}
              className="flex-1 px-4 py-2 rounded-lg text-sm font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={provision.isPending}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg font-medium transition-colors"
            >
              {provision.isPending ? 'Provisioning…' : 'Provision'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Credentials Modal */}
      <CredentialsModal db={credentialsDB} onClose={() => setCredentialsDB(null)} />

      {/* Confirm Delete */}
      <ConfirmDialog
        isOpen={confirmDeleteId != null}
        onClose={() => setConfirmDeleteId(null)}
        onConfirm={() => deprovision.mutate(confirmDeleteId)}
        title="Deprovision Database"
        message="This will permanently destroy the database instance and all its data. This action cannot be undone."
        confirmLabel="Deprovision"
        danger
      />
    </div>
  )
}
