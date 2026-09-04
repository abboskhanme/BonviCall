/**
 * Alerts — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * The scheduler raises these on a timer: silence sweeps, capability drift,
 * offline detection, receiver health, job failures. This is where R3 and R17
 * become visible to a human, so the list polls fast (SPEC §5.3).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { POLL_FAST_MS } from '@/app/queryClient'
import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type Alert = components['schemas']['AlertResponse']
export type AlertList = components['schemas']['AlertListResponse']
export type AlertQuery = NonNullable<operations['list_alerts_api_v1_alerts_get']['parameters']['query']>

export function useAlerts(params: AlertQuery): UseQueryResult<AlertList> {
  return useQuery({
    queryKey: queryKey('alerts', 'list', params),
    queryFn: () => api.get<AlertList>('/alerts', { ...params }),
    refetchInterval: POLL_FAST_MS,
  })
}

/**
 * Acknowledge. `alerts:ack` is admin-only (SPEC §4.1), so a manager sees the
 * list and not the button — they are meant to act on it, not file it.
 */
export function useAcknowledgeAlert(): UseMutationResult<Alert, unknown, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (alertId: string) => api.post<Alert>(`/alerts/${alertId}/ack`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('alerts') })
    },
  })
}
