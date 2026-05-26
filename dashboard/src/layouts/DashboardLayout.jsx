import { Outlet, useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import { usePrewarmVM } from '../hooks/useVMs'
import Sidebar from '../components/shared/Sidebar'
import Topbar from '../components/shared/Topbar'

const TITLE_MAP = {
  '/dashboard': 'Overview',
  '/dashboard/vms': 'Virtual Machines',
  '/dashboard/containers': 'Containers',
  '/dashboard/storage': 'Storage',
  '/dashboard/databases': 'Databases',
  '/dashboard/settings': 'Settings',
}

export default function DashboardLayout() {
  const location = useLocation()
  const title = TITLE_MAP[location.pathname] || 'Dashboard'
  const prewarm = usePrewarmVM()

  useEffect(() => {
    // Silently initiate VM boot/resume in the background
    prewarm.mutate()
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Topbar title={title} />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
