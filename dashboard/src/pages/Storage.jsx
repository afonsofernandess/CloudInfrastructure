import { useState, useRef } from 'react'
import { HardDrive, Upload, Download, Trash2, FileText, Plus, Disc, Files, Clock } from 'lucide-react'
import { useFiles, useUploadFile, useDeleteFile, useDisks, useCreateDisk, useDeleteDisk } from '../hooks/useFiles'
import { downloadFile } from '../api/storage'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import EmptyState from '../components/shared/EmptyState'
import SkeletonTable from '../components/shared/SkeletonTable'
import { formatBytes, formatDate } from '../utils/formatters'
import clsx from 'clsx'
import toast from 'react-hot-toast'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export default function Storage() {
  const [activeTab, setActiveTab] = useState('files') // 'files' | 'disks'

  // Files state/hooks
  const { data: files, isLoading: filesLoading } = useFiles()
  const uploadFile = useUploadFile()
  const deleteFile = useDeleteFile()
  const [isDragging, setIsDragging] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(null)
  const [confirmDeleteFilename, setConfirmDeleteFilename] = useState(null)
  const fileInputRef = useRef(null)

  // Disks state/hooks
  const { data: disks, isLoading: disksLoading } = useDisks()
  const createDisk = useCreateDisk()
  const deleteDisk = useDeleteDisk()
  const [newDiskName, setNewDiskName] = useState('')
  const [newDiskSize, setNewDiskSize] = useState(5) // default 5 GB
  const [confirmDeleteDiskId, setConfirmDeleteDiskId] = useState(null)

  // Files Handlers
  const handleFiles = (fileList) => {
    if (!fileList?.length) return
    const file = fileList[0]
    setUploadProgress(0)
    uploadFile.mutate(
      { file, onProgress: setUploadProgress },
      {
        onSuccess: () => setUploadProgress(null),
        onError: () => setUploadProgress(null),
      }
    )
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => setIsDragging(false)

  const handleDownload = async (filename) => {
    try {
      await downloadFile(filename)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Download failed', toastStyle)
    }
  }

  // Disks Handlers
  const handleCreateDisk = (e) => {
    e.preventDefault()
    if (!newDiskName.trim()) {
      toast.error('Please enter a disk name', toastStyle)
      return
    }
    if (newDiskSize <= 0) {
      toast.error('Disk size must be greater than 0 GB', toastStyle)
      return
    }
    createDisk.mutate(
      { name: newDiskName.trim(), size_gb: parseInt(newDiskSize) },
      {
        onSuccess: () => {
          setNewDiskName('')
          setNewDiskSize(5)
        },
      }
    )
  }

  const totalSize = files?.reduce((sum, f) => sum + (f.size_bytes || 0), 0) ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Storage</h1>
          <p className="text-sm text-slate-400 mt-1">Manage object storage buckets and block storage disks</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-700">
        <button
          onClick={() => setActiveTab('files')}
          className={clsx(
            'flex items-center gap-2 px-6 py-3 font-semibold text-sm border-b-2 -mb-px transition-all',
            activeTab === 'files'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          )}
        >
          <Files className="w-4 h-4" />
          Object Storage (Files)
        </button>
        <button
          onClick={() => setActiveTab('disks')}
          className={clsx(
            'flex items-center gap-2 px-6 py-3 font-semibold text-sm border-b-2 -mb-px transition-all',
            activeTab === 'disks'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          )}
        >
          <Disc className="w-4 h-4" />
          Block Storage (Disks)
        </button>
      </div>

      {/* Active Tab View */}
      {activeTab === 'files' ? (
        <div className="space-y-6">
          {/* Upload Area */}
          <div
            className={clsx(
              'border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer',
              isDragging
                ? 'border-blue-500 bg-blue-500/10'
                : 'border-slate-600 bg-slate-900 hover:border-slate-500 hover:bg-slate-800/50'
            )}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
            />
            <Upload className={clsx('w-10 h-10 mx-auto mb-3', isDragging ? 'text-blue-400' : 'text-slate-500')} />
            <p className="text-slate-300 font-medium">
              {isDragging ? 'Drop to upload' : 'Click or drag & drop to upload'}
            </p>
            <p className="text-slate-500 text-sm mt-1">Any file type supported</p>

            {uploadProgress != null && (
              <div className="mt-4 max-w-xs mx-auto">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Uploading…</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Files List */}
          <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
            {filesLoading ? (
              <div className="p-4">
                <SkeletonTable rows={4} cols={4} />
              </div>
            ) : !files?.length ? (
              <EmptyState
                icon={HardDrive}
                title="No files uploaded"
                description="Upload your first file using the area above"
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-800 text-slate-400 uppercase text-xs tracking-wider">
                      <th className="px-4 py-3 text-left">Filename</th>
                      <th className="px-4 py-3 text-left">Size</th>
                      <th className="px-4 py-3 text-left">Last Modified</th>
                      <th className="px-4 py-3 text-left">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((file) => (
                      <tr key={file.filename} className="border-b border-slate-700 hover:bg-slate-800/50 transition-colors">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <FileText className="w-4 h-4 text-slate-500 shrink-0" />
                            <span className="text-slate-100 font-mono text-xs">{file.filename}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-400">{formatBytes(file.size_bytes)}</td>
                        <td className="px-4 py-3 text-slate-400">{formatDate(file.last_modified)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleDownload(file.filename)}
                              className="p-1.5 rounded text-blue-400 hover:bg-blue-500/10 transition-colors"
                              title="Download"
                            >
                              <Download className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => setConfirmDeleteFilename(file.filename)}
                              className="p-1.5 rounded text-red-400 hover:bg-red-500/10 transition-colors"
                              title="Delete"
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
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Create Disk Panel */}
          <div className="lg:col-span-1 bg-slate-900 border border-slate-700 rounded-xl p-6 h-fit space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-700 pb-3">
              <Plus className="w-5 h-5 text-blue-400" />
              <h2 className="text-lg font-semibold text-slate-200">Create Virtual Disk</h2>
            </div>
            <form onSubmit={handleCreateDisk} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                  Disk Name
                </label>
                <input
                  type="text"
                  value={newDiskName}
                  onChange={(e) => setNewDiskName(e.target.value)}
                  placeholder="e.g. data-volume-1"
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex justify-between">
                  <span>Storage Size</span>
                  <span className="text-blue-400">{newDiskSize} GB</span>
                </label>
                <input
                  type="range"
                  min="1"
                  max="100"
                  value={newDiskSize}
                  onChange={(e) => setNewDiskSize(parseInt(e.target.value))}
                  className="w-full accent-blue-500"
                />
                <div className="flex justify-between text-xs text-slate-500 mt-1">
                  <span>1 GB</span>
                  <span>50 GB</span>
                  <span>100 GB</span>
                </div>
              </div>
              <button
                type="submit"
                disabled={createDisk.isPending}
                className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white font-semibold text-sm py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                {createDisk.isPending ? 'Allocating...' : 'Create Disk'}
              </button>
            </form>
          </div>

          {/* Disk Listing Table */}
          <div className="lg:col-span-2 bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
            <div className="p-4 border-b border-slate-700 flex justify-between items-center bg-slate-800/30">
              <h2 className="text-md font-semibold text-slate-300">Disk Volumes (OpenNebula Block Storage)</h2>
            </div>
            {disksLoading ? (
              <div className="p-4">
                <SkeletonTable rows={3} cols={5} />
              </div>
            ) : !disks?.length ? (
              <EmptyState
                icon={Disc}
                title="No virtual disks allocated"
                description="Use the panel on the left to allocate persistent block storage disks in OpenNebula"
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-800 text-slate-400 uppercase text-xs tracking-wider">
                      <th className="px-4 py-3 text-left">Disk ID</th>
                      <th className="px-4 py-3 text-left">Name</th>
                      <th className="px-4 py-3 text-left">Size</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3 text-left">Created At</th>
                      <th className="px-4 py-3 text-left">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {disks.map((disk) => (
                      <tr key={disk.id} className="border-b border-slate-700 hover:bg-slate-800/50 transition-colors">
                        <td className="px-4 py-3 text-slate-400 font-mono text-xs">#{disk.one_image_id}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Disc className="w-4 h-4 text-blue-400 shrink-0" />
                            <span className="text-slate-100 font-semibold">{disk.name}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-300">{disk.size_gb} GB</td>
                        <td className="px-4 py-3">
                          <span
                            className={clsx(
                              'px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wider',
                              disk.status === 'READY' && 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
                              disk.status === 'USED' && 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
                              (disk.status === 'LOCKED' || disk.status === 'CLONE' || disk.status === 'INIT') &&
                                'bg-amber-500/10 text-amber-400 border border-amber-500/20',
                              disk.status === 'ERROR' && 'bg-red-500/10 text-red-400 border border-red-500/20',
                              disk.status === 'DISABLED' && 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                            )}
                          >
                            {disk.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400">
                          <div className="flex items-center gap-1.5 text-xs">
                            <Clock className="w-3.5 h-3.5 text-slate-500" />
                            {formatDate(disk.created_at)}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setConfirmDeleteDiskId(disk.id)}
                            className="p-1.5 rounded text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Delete Disk"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Delete File Confirm Dialog */}
      <ConfirmDialog
        isOpen={confirmDeleteFilename != null}
        onClose={() => setConfirmDeleteFilename(null)}
        onConfirm={() => deleteFile.mutate(confirmDeleteFilename)}
        title="Delete File"
        message={`Are you sure you want to delete "${confirmDeleteFilename}"? This cannot be undone.`}
        confirmLabel="Delete"
        danger
      />

      {/* Delete Disk Confirm Dialog */}
      <ConfirmDialog
        isOpen={confirmDeleteDiskId != null}
        onClose={() => setConfirmDeleteDiskId(null)}
        onConfirm={() => {
          deleteDisk.mutate(confirmDeleteDiskId)
          setConfirmDeleteDiskId(null)}
        }
        title="Delete Virtual Disk"
        message="Are you sure you want to delete this virtual disk volume? All data stored on it will be permanently lost."
        confirmLabel="Delete Volume"
        danger
      />
    </div>
  )
}
