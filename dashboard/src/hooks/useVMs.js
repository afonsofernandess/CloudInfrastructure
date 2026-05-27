import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { listVMs, createVM, getVM, destroyVM, prewarmVM, listTemplates } from '../api/compute'

export function useVMs() {
  return useQuery({
    queryKey: ['vms'],
    queryFn: listVMs,
    refetchInterval: 10000,
  })
}

export function useVM(id) {
  return useQuery({
    queryKey: ['vms', id],
    queryFn: () => getVM(id),
    refetchInterval: 10000,
    enabled: !!id,
  })
}

export function useCreateVM() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createVM,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vms'] })
      toast.success('VM launched successfully', {
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, {
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
    },
  })
}

export function useDestroyVM() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: destroyVM,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vms'] })
      toast.success('VM destroyed', {
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
    },
    onError: (err) => {
      toast.error(err.response?.data?.detail || err.message, {
        style: { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' },
      })
    },
  })
}

export function usePrewarmVM() {
  return useMutation({
    mutationFn: prewarmVM,
  })
}

export function useTemplates() {
  return useQuery({
    queryKey: ['templates'],
    queryFn: listTemplates,
  })
}
