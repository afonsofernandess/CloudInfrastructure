import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { User, Lock, AlertTriangle, Eye, EyeOff, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { updateMe, deleteMe } from '../api/auth'
import useAuthStore from '../store/authStore'
import Modal from '../components/shared/Modal'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

function SectionCard({ title, icon: Icon, children }) {
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-xl p-6">
      <div className="flex items-center gap-2 mb-5">
        <Icon className="w-5 h-5 text-blue-400" />
        <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
      </div>
      {children}
    </div>
  )
}

export default function Settings() {
  const navigate = useNavigate()
  const { user, setUser, logout } = useAuthStore()

  const [email, setEmail] = useState(user?.email || '')
  const [emailLoading, setEmailLoading] = useState(false)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [pwLoading, setPwLoading] = useState(false)
  const [pwError, setPwError] = useState('')

  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleteLoading, setDeleteLoading] = useState(false)

  useEffect(() => {
    if (user?.email) setEmail(user.email)
  }, [user])

  const handleUpdateEmail = async (e) => {
    e.preventDefault()
    setEmailLoading(true)
    try {
      const updated = await updateMe({ email })
      setUser(updated)
      toast.success('Email updated', toastStyle)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Update failed', toastStyle)
    } finally {
      setEmailLoading(false)
    }
  }

  const handleUpdatePassword = async (e) => {
    e.preventDefault()
    setPwError('')
    if (newPw !== confirmPw) {
      setPwError('Passwords do not match')
      return
    }
    if (newPw.length < 6) {
      setPwError('Password must be at least 6 characters')
      return
    }
    setPwLoading(true)
    try {
      await updateMe({ password: newPw })
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
      toast.success('Password updated', toastStyle)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Update failed', toastStyle)
    } finally {
      setPwLoading(false)
    }
  }

  const handleDeleteAccount = async () => {
    if (deleteConfirmText !== user?.username) return
    setDeleteLoading(true)
    try {
      await deleteMe()
      toast.success('Account deleted', toastStyle)
      logout()
      navigate('/login')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Delete failed', toastStyle)
      setDeleteLoading(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">Settings</h1>
        <p className="text-sm text-slate-400 mt-1">Manage your account preferences</p>
      </div>

      {/* Profile section */}
      <SectionCard title="Profile" icon={User}>
        <form onSubmit={handleUpdateEmail} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Username</label>
            <input
              type="text"
              value={user?.username || ''}
              readOnly
              className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-slate-400 w-full cursor-not-allowed"
            />
            <p className="text-xs text-slate-500 mt-1">Username cannot be changed</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
            />
          </div>
          {user?.one_user_id && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">OpenNebula User ID</label>
              <input
                type="text"
                value={user.one_user_id}
                readOnly
                className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-slate-400 w-full cursor-not-allowed font-mono text-sm"
              />
            </div>
          )}
          <button
            type="submit"
            disabled={emailLoading}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
          >
            {emailLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            Save Changes
          </button>
        </form>
      </SectionCard>

      {/* Change Password section */}
      <SectionCard title="Change Password" icon={Lock}>
        <form onSubmit={handleUpdatePassword} className="space-y-4">
          {pwError && (
            <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
              {pwError}
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Current Password</label>
            <input
              type="password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              required
              placeholder="••••••••"
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">New Password</label>
            <div className="relative">
              <input
                type={showPw ? 'text' : 'password'}
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                required
                placeholder="••••••••"
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 pr-10 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
              />
              <button
                type="button"
                onClick={() => setShowPw(!showPw)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors"
              >
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Confirm New Password</label>
            <input
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              required
              placeholder="••••••••"
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full"
            />
          </div>
          <button
            type="submit"
            disabled={pwLoading}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center gap-2"
          >
            {pwLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            Update Password
          </button>
        </form>
      </SectionCard>

      {/* Danger Zone */}
      <div className="bg-slate-900 border border-red-800/50 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-5 h-5 text-red-400" />
          <h2 className="text-lg font-semibold text-red-400">Danger Zone</h2>
        </div>
        <p className="text-sm text-slate-400 mb-4">
          Deleting your account will permanently remove all your data, VMs, containers, databases, and files. This action cannot be undone.
        </p>
        <button
          onClick={() => setShowDeleteModal(true)}
          className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg font-medium transition-colors focus:ring-2 focus:ring-red-500 focus:outline-none"
        >
          Delete Account
        </button>
      </div>

      {/* Delete Account Modal */}
      <Modal isOpen={showDeleteModal} onClose={() => { setShowDeleteModal(false); setDeleteConfirmText('') }} title="Delete Account">
        <div className="space-y-4">
          <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30">
            <p className="text-red-400 text-sm font-medium">This action is irreversible</p>
            <p className="text-red-400/80 text-sm mt-1">All your data will be permanently deleted.</p>
          </div>
          <div>
            <label className="block text-sm text-slate-300 mb-1.5">
              Type <span className="font-mono font-bold text-slate-100">{user?.username}</span> to confirm
            </label>
            <input
              type="text"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder={user?.username}
              className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-100 focus:ring-2 focus:ring-red-500 focus:outline-none w-full"
            />
          </div>
          <div className="flex gap-3 pt-2">
            <button
              onClick={() => { setShowDeleteModal(false); setDeleteConfirmText('') }}
              className="flex-1 px-4 py-2 rounded-lg text-sm font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDeleteAccount}
              disabled={deleteConfirmText !== user?.username || deleteLoading}
              className="flex-1 bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
            >
              {deleteLoading && <Loader2 className="w-4 h-4 animate-spin" />}
              Delete Account
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
