import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export function useVMMetrics(vmId) {
  return useQuery({
    queryKey: ['vm-metrics', vmId],
    queryFn: async () => {
      const response = await api.get(`/compute/vms/${vmId}/metrics`)
      return response.data
    },
    enabled: !!vmId,
    refetchInterval: 30000, // Sync with backend recorder
  })
}

export function useEnergyStats() {
  return useQuery({
    queryKey: ['energy-stats'],
    queryFn: async () => {
      const response = await api.get('/compute/energy-stats')
      return response.data
    },
    refetchInterval: 60000,
  })
}
