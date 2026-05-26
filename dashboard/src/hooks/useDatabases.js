import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listDatabases, provisionDB, deprovisionDB } from '../api/databases'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export function useDatabases() {
  return useQuery({
    queryKey: ['databases'],
    queryFn: listDatabases,
    refetchInterval: 10000,
  })
}

export function useProvisionDB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: provisionDB,
    onSuccess: (newDB) => {
      // Instantly show the new database
      queryClient.setQueryData(['databases'], (old) =>
        old ? [newDB, ...old] : [newDB]
      )
      // Sync from server in background
      queryClient.refetchQueries({ queryKey: ['databases'] })
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
    onMutate: async (id) => {
      // Optimistically remove from list immediately
      await queryClient.cancelQueries({ queryKey: ['databases'] })
      const prev = queryClient.getQueryData(['databases'])
      queryClient.setQueryData(['databases'], (old) =>
        old?.filter((db) => db.id !== id) ?? []
      )
      return { prev }
    },
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['databases'] })
      toast.success('Database deprovisioned', toastStyle)
    },
    onError: (err, _variables, context) => {
      // Roll back on error
      if (context?.prev) queryClient.setQueryData(['databases'], context.prev)
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}
