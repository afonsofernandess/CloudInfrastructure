import { useQuery, useMutation, useQueryClient, useIsMutating } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listDatabases, provisionDB, deprovisionDB, deleteCluster, restartDB } from '../api/databases'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export function useDatabases() {
  const isMutating = useIsMutating()
  return useQuery({
    queryKey: ['databases'],
    queryFn: listDatabases,
    refetchInterval: isMutating > 0 ? false : 10000,
  })
}

export function useProvisionDB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: provisionDB,
    onSuccess: (newDB) => {
      if (newDB && newDB.primary) {
        // It's a DBClusterResponse! Just refetch directly to get all instances
        queryClient.refetchQueries({ queryKey: ['databases'] })
      } else {
        // It's a single DBInstance! Optimistically update
        queryClient.setQueryData(['databases'], (old) =>
          old ? [newDB, ...old] : [newDB]
        )
        queryClient.refetchQueries({ queryKey: ['databases'] })
      }
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

export function useDeleteCluster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteCluster,
    onMutate: async (clusterName) => {
      await queryClient.cancelQueries({ queryKey: ['databases'] })
      const prev = queryClient.getQueryData(['databases'])
      // Optimistically remove all rows belonging to this cluster
      queryClient.setQueryData(['databases'], (old) =>
        old?.filter((db) => db.cluster_name !== clusterName) ?? []
      )
      return { prev }
    },
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['databases'] })
      toast.success('Cluster deleted', toastStyle)
    },
    onError: (err, _variables, context) => {
      if (context?.prev) queryClient.setQueryData(['databases'], context.prev)
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useRestartDB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: restartDB,
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['databases'] })
      toast.success('Container restart initiated', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}
