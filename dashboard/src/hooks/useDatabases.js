import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listDatabases, provisionDB, deprovisionDB } from '../api/databases'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export function useDatabases() {
  return useQuery({
    queryKey: ['databases'],
    queryFn: listDatabases,
  })
}

export function useProvisionDB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: provisionDB,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['databases'] })
      toast.success('Database provisioned', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useDeprovisionDB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deprovisionDB,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['databases'] })
      toast.success('Database deprovisioned', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}
