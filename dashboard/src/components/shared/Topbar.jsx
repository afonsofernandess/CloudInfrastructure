import { useNavigate } from 'react-router-dom'
import { Sun, Moon, LogOut, User } from 'lucide-react'
import { useState, useEffect } from 'react'
import useAuthStore from '../../store/authStore'

export default function Topbar({ title }) {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark'))

  useEffect(() => {
    const stored = localStorage.getItem('theme')
    if (stored === 'light') {
      document.documentElement.classList.remove('dark')
      setIsDark(false)
    } else {
      document.documentElement.classList.add('dark')
      setIsDark(true)
    }
  }, [])

  const toggleTheme = () => {
    const next = !isDark
    setIsDark(next)
    if (next) {
      document.documentElement.classList.add('dark')
      localStorage.setItem('theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="h-14 flex items-center justify-between px-6 bg-slate-900 border-b border-slate-700 shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-slate-500 text-sm">Dashboard</span>
        {title && title !== 'Overview' && (
          <>
            <span className="text-slate-600">/</span>
            <span className="text-slate-100 text-sm font-medium">{title}</span>
          </>
        )}
        {title === 'Overview' && (
          <span className="text-slate-100 text-sm font-medium">Overview</span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition-colors focus:ring-2 focus:ring-blue-500 focus:outline-none"
          title="Toggle theme"
        >
          {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800">
          <User className="w-4 h-4 text-slate-400" />
          <span className="text-sm text-slate-300">{user?.username || 'User'}</span>
        </div>

        <button
          onClick={handleLogout}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-slate-400 hover:bg-red-500/10 hover:text-red-400 transition-colors text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
          title="Logout"
        >
          <LogOut className="w-4 h-4" />
          <span className="hidden sm:inline">Logout</span>
        </button>
      </div>
    </header>
  )
}
