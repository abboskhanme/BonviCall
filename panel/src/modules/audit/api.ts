/**
 * Audit log — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * Read-only by construction: there is no mutation here and no delete
 * affordance anywhere in the module, because an audit log somebody can edit is
 * not an audit log (SPEC §5.2).
 */
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type AuditEntry = components['schemas']['AuditResponse']
export type AuditList = components['schemas']['AuditListResponse']
export type AuditQuery = NonNullable<
  operations['list_audit_api_v1_audit_get']['parameters']['query']
>

export function useAudit(params: AuditQuery): UseQueryResult<AuditList> {
  return useQuery({
    queryKey: queryKey('audit', 'list', params),
    queryFn: () => api.get<AuditList>('/audit', { ...params }),
  })
}
