import { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Server,
  Box,
  HardDrive,
  Database,
  Settings,
  ChevronLeft,
  ChevronRight,
  Cloud,
} from 'lucide-react'
import clsx from 'clsx'

const NAV_ITEMS = [
  { label: 'Overview', path: '/dashboard', icon: LayoutDashboard, end: true },
  { label: 'VMs', path: '/dashboard/vms', icon: Server },
  { label: 'Containers', path: '/dashboard/containers', icon: Box },
  { label: 'Storage', path: '/dashboard/storage', icon: HardDrive },
  { label: 'Databases', path: '/dashboard/databases', icon: Database },
  { label: 'Settings', path: '/dashboard/settings', icon: Settings },
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem('sidebar_collapsed') === 'true'
  })

  const toggleCollapsed = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('sidebar_collapsed', String(next))
  }

  return (
    <aside
      className={clsx(
        'flex flex-col bg-slate-900 border-r border-slate-700 h-full transition-all duration-300',
        collapsed ? 'w-16' : 'w-56'
      )}
    >
      {/* Logo */}
      <div className={clsx('flex items-center gap-3 px-4 py-5 border-b border-slate-700', collapsed && 'justify-center px-2')}>
        <Cloud className="w-7 h-7 text-blue-400 shrink-0" />
        {!collapsed && <span className="text-slate-100 font-bold text-lg leading-none">Cloud</span>}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ label, path, icon: Icon, end }) => (
          <NavLink
            key={path}
            to={path}
            end={end}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors group',
                collapsed && 'justify-center px-2',
                isActive
                  ? 'bg-blue-600/20 text-blue-400'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon className={clsx('w-5 h-5 shrink-0', isActive ? 'text-blue-400' : 'text-slate-400 group-hover:text-slate-100')} />
                {!collapsed && <span>{label}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="p-2 border-t border-slate-700">
        <button
          onClick={toggleCollapsed}
          className="w-full flex items-center justify-center p-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronLeft className="w-5 h-5" />}
        </button>
      </div>
    </aside>
  )
}
