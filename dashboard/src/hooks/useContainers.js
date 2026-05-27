import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listContainers, launchContainer, startContainer, stopContainer, removeContainer, getContainerLogs } from '../api/containers'

const toastStyle = { style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' } }

export function useContainers() {
  return useQuery({
    queryKey: ['containers'],
    queryFn: listContainers,
    refetchInterval: 10000,
  })
}

export function useLaunchContainer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: launchContainer,
    onSuccess: (newContainer) => {
      // Instantly inject the new container into the cache
      queryClient.setQueryData(['containers'], (old) =>
        old ? [newContainer, ...old] : [newContainer]
      )
      // Then sync from server in background
      queryClient.refetchQueries({ queryKey: ['containers'] })
      toast.success('Container launched', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useStartContainer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: startContainer,
    onSuccess: (updated) => {
      queryClient.setQueryData(['containers'], (old) =>
        old?.map((c) => c.container_id === updated.container_id ? { ...c, ...updated } : c) ?? []
      )
      queryClient.refetchQueries({ queryKey: ['containers'] })
      toast.success('Container started', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useStopContainer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: stopContainer,
    onSuccess: (updated) => {
      queryClient.setQueryData(['containers'], (old) =>
        old?.map((c) => c.container_id === updated.container_id ? { ...c, ...updated } : c) ?? []
      )
      queryClient.refetchQueries({ queryKey: ['containers'] })
      toast.success('Container stopped', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useRemoveContainer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: removeContainer,
    onMutate: async (container_id) => {
      // Optimistically remove from the list immediately
      await queryClient.cancelQueries({ queryKey: ['containers'] })
      const prev = queryClient.getQueryData(['containers'])
      queryClient.setQueryData(['containers'], (old) =>
        old?.filter((c) => c.container_id !== container_id) ?? []
      )
      return { prev }
    },
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['containers'] })
      toast.success('Container removed', toastStyle)
    },
    onError: (err, _variables, context) => {
      // Roll back optimistic removal on error
      if (context?.prev) queryClient.setQueryData(['containers'], context.prev)
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}

export function useContainerLogs(id, enabled = false, tail = 100) {
  return useQuery({
    queryKey: ['containers', id, 'logs', tail],
    queryFn: () => getContainerLogs(id, tail),
    enabled: !!id && enabled,
    refetchInterval: 3000, // Poll every 3 seconds for live-updating logs
  })
}
