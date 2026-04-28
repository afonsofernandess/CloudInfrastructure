import { useQuery } from '@tanstack/react-query'
import { getClusterStatus } from '../api/compute'

export function useClusterStatus() {
  return useQuery({
    queryKey: ['cluster-status'],
    queryFn: getClusterStatus,
    refetchInterval: 10000,
  })
}
