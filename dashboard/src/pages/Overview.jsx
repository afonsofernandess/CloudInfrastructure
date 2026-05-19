import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { Server, Box, Database, Cpu, Activity, Plus, CheckCircle, XCircle, Leaf } from 'lucide-react'
import { useClusterStatus } from '../hooks/useClusterStatus'
import { useContainers } from '../hooks/useContainers'
import { useDatabases } from '../hooks/useDatabases'
import { useEnergyStats } from '../hooks/useMetrics'
import { formatTime } from '../utils/formatters'
import clsx from 'clsx'

function StatCard({ icon: Icon, label, value, sub, color = 'text-blue-400' }) {
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{label}</span>
        <Icon className={clsx('w-5 h-5', color)} />
      </div>
      <div className="text-3xl font-bold text-slate-100">{value ?? '—'}</div>
      {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
    </div>
  )
}

export default function Overview() {
  const navigate = useNavigate()
  const { data: cluster } = useClusterStatus()
  const { data: containers } = useContainers()
  const { data: databases } = useDatabases()

  const chartDataRef = useRef([])
  const [chartData, setChartData] = useState([])

  useEffect(() => {
    if (cluster == null) return
    const point = {
      time: formatTime(new Date()),
      cpu: cluster.avg_cpu_pct ?? 0,
    }
    const next = [...chartDataRef.current, point].slice(-20)
    chartDataRef.current = next
    setChartData([...next])
  }, [cluster])

  const { data: energy } = useEnergyStats()

  const runningContainers = containers?.filter((c) => c.status === 'running').length ?? 0
  const activeDatabases = databases?.filter((d) => d.status === 'running').length ?? 0

  const avgCpu = cluster?.avg_cpu_pct ?? 0
  const cpuColor = avgCpu > 80 ? 'text-red-400' : avgCpu > 60 ? 'text-yellow-400' : 'text-green-400'

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
        <StatCard icon={Server} label="Total VMs" value={cluster?.total_vms ?? 0} />
        <StatCard icon={Activity} label="Active VMs" value={cluster?.active_vms ?? 0} color="text-green-400" />
        <StatCard icon={Cpu} label="Avg CPU" value={`${avgCpu.toFixed(1)}%`} color={cpuColor} />
        <StatCard icon={Box} label="Running Containers" value={runningContainers} color="text-purple-400" />
        <StatCard icon={Database} label="Active Databases" value={activeDatabases} color="text-orange-400" />
      </div>

      {/* CPU Chart */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Cluster CPU over time</h2>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#f1f5f9' }}
              labelStyle={{ color: '#94a3b8' }}
            />
            <Area type="monotone" dataKey="cpu" stroke="#3b82f6" strokeWidth={2} fill="url(#cpuGrad)" dot={false} name="CPU %" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Bottom panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Autoscaler panel */}
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Autoscaler</h2>
          <div className="flex items-center gap-2">
            {cluster?.autoscaler_enabled ? (
              <CheckCircle className="w-5 h-5 text-green-400" />
            ) : (
              <XCircle className="w-5 h-5 text-red-400" />
            )}
            <span className={clsx('text-sm font-medium', cluster?.autoscaler_enabled ? 'text-green-400' : 'text-red-400')}>
              {cluster?.autoscaler_enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-400 block text-xs mb-0.5">Min VMs</span>
              <span className="text-slate-100 font-semibold">{cluster?.min_vms ?? '—'}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-xs mb-0.5">Max VMs</span>
              <span className="text-slate-100 font-semibold">{cluster?.max_vms ?? '—'}</span>
            </div>
          </div>
          {/* VM utilization bar */}
          {cluster && (
            <div>
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Capacity Usage</span>
                <span>{cluster.total_vms} / {cluster.max_vms}</span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all"
                  style={{ width: `${Math.min(100, (cluster.total_vms / (cluster.max_vms || 1)) * 100)}%` }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Energy Savings panel */}
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 space-y-4">
          <h2 className="text-sm font-semibold text-green-400 uppercase tracking-wider flex items-center gap-2">
            <Leaf className="w-4 h-4" />
            Sustainability
          </h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-slate-400 block text-xs mb-0.5">Hours Saved</span>
              <span className="text-slate-100 font-bold text-lg">{energy?.hours_saved ?? 0}h</span>
            </div>
            <div>
              <span className="text-slate-400 block text-xs mb-0.5">Energy Saved</span>
              <span className="text-green-400 font-bold text-lg">{energy?.energy_saved_kwh ?? 0} kWh</span>
            </div>
            <div className="col-span-2 pt-2 border-t border-slate-800">
               <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-400 uppercase tracking-wider">CO2 Reduction</span>
                  <span className="text-sm font-semibold text-slate-100">{energy?.co2_saved_kg ?? 0} kg</span>
               </div>
               <div className="text-[10px] text-slate-500 mt-1 italic">* Estimated vs max capacity baseline</div>
            </div>
          </div>
        </div>

        {/* Quick actions */}
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Quick Actions</h2>
          <div className="space-y-3">
            <button
              onClick={() => navigate('/dashboard/vms')}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-100 transition-colors"
            >
              <div className="p-1.5 bg-blue-600/20 rounded-lg">
                <Server className="w-4 h-4 text-blue-400" />
              </div>
              <div className="text-left">
                <div className="text-xs font-medium">Launch VM</div>
              </div>
              <Plus className="w-3 h-3 text-slate-400 ml-auto" />
            </button>

            <button
              onClick={() => navigate('/dashboard/containers')}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-100 transition-colors"
            >
              <div className="p-1.5 bg-purple-600/20 rounded-lg">
                <Box className="w-4 h-4 text-purple-400" />
              </div>
              <div className="text-left">
                <div className="text-xs font-medium">New Container</div>
              </div>
              <Plus className="w-3 h-3 text-slate-400 ml-auto" />
            </button>

            <button
              onClick={() => navigate('/dashboard/databases')}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-100 transition-colors"
            >
              <div className="p-1.5 bg-orange-600/20 rounded-lg">
                <Database className="w-4 h-4 text-orange-400" />
              </div>
              <div className="text-left">
                <div className="text-xs font-medium">New Database</div>
              </div>
              <Plus className="w-3 h-3 text-slate-400 ml-auto" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
