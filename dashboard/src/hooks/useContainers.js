import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listContainers, launchContainer, startContainer, stopContainer, removeContainer } from '../api/containers'

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
      toast.success('Container removed', toastStyle)
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, toastStyle)
    },
  })
}
