import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listFiles, uploadFile, deleteFile, listDisks, createDisk, deleteDisk } from '../api/storage'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export function useFiles() {
  return useQuery({
    queryKey: ['files'],
    queryFn: listFiles,
  })
}

export function useUploadFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, onProgress }) => uploadFile(file, onProgress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files'] })
      toast.success('File uploaded', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useDeleteFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteFile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files'] })
      toast.success('File deleted', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useDisks() {
  return useQuery({
    queryKey: ['disks'],
    queryFn: listDisks,
    refetchInterval: 10000,
  })
}

export function useCreateDisk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createDisk,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['disks'] })
      toast.success('Disk created successfully', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useDeleteDisk() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteDisk,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['disks'] })
      toast.success('Disk deleted successfully', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

