import { useState, useRef } from 'react'
import { HardDrive, Upload, Download, Trash2, FileText } from 'lucide-react'
import { useFiles, useUploadFile, useDeleteFile } from '../hooks/useFiles'
import { downloadFile } from '../api/storage'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import EmptyState from '../components/shared/EmptyState'
import SkeletonTable from '../components/shared/SkeletonTable'
import { formatBytes, formatDate } from '../utils/formatters'
import clsx from 'clsx'
import toast from 'react-hot-toast'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export default function Storage() {
  const { data: files, isLoading } = useFiles()
  const uploadFile = useUploadFile()
  const deleteFile = useDeleteFile()

  const [isDragging, setIsDragging] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(null)
  const [confirmDeleteFilename, setConfirmDeleteFilename] = useState(null)
  const fileInputRef = useRef(null)

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

  const totalSize = files?.reduce((sum, f) => sum + (f.size_bytes || 0), 0) ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Storage</h1>
          <p className="text-sm text-slate-400 mt-1">Manage your files and objects</p>
        </div>
        {files?.length > 0 && (
          <div className="text-sm text-slate-400 bg-slate-900 border border-slate-700 px-4 py-2 rounded-lg">
            {files.length} file{files.length !== 1 ? 's' : ''} — {formatBytes(totalSize)} total
          </div>
        )}
      </div>

      {/* Upload area */}
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

      {/* File list */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
        {isLoading ? (
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

      <ConfirmDialog
        isOpen={confirmDeleteFilename != null}
        onClose={() => setConfirmDeleteFilename(null)}
        onConfirm={() => deleteFile.mutate(confirmDeleteFilename)}
        title="Delete File"
        message={`Are you sure you want to delete "${confirmDeleteFilename}"? This cannot be undone.`}
        confirmLabel="Delete"
        danger
      />
    </div>
  )
}
