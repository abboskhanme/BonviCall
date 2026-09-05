/**
 * The line directory — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This is what makes a call **internal** (UC-25). Registered numbers feed the
 * directory automatically, so this page is the EXTRAS: office lines, the
 * warehouse, a director's second mobile — anything that is "us" without being
 * an agent's handset.
 *
 * **It starves if nobody tends it, and a starved directory is worse than
 * none.** BonviZvonki's had 10 of 33 employees in it, so twenty-three people's
 * internal calls were filed as external and every "external call volume"
 * number it produced was wrong — silently, and in the direction that looks
 * like more business. Ours is empty today and every one of the 52 calls on the
 * server is classified `external`, which is the same failure at the start
 * rather than in the middle.
 *
 * `ReclassifyResponse.calls_reclassified` is why a change here is not a
 * settings edit: adding a rule rewrites the classification of calls that
 * already happened, and the page says how many.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type DirectoryEntry = components['schemas']['DirectoryEntryResponse']
export type DirectoryEntryList = components['schemas']['DirectoryEntryListResponse']
export type CreateDirectoryEntryRequest = components['schemas']['CreateDirectoryEntryRequest']
export type ReclassifyResponse = components['schemas']['ReclassifyResponse']
export type DirectoryRuleKind = components['schemas']['DirectoryRuleKind']

export function useLineDirectory(enabled: boolean): UseQueryResult<DirectoryEntryList> {
  return useQuery({
    queryKey: queryKey('settings', 'lineDirectory'),
    queryFn: () => api.get<DirectoryEntryList>('/line-directory'),
    enabled,
  })
}

/** Adding a rule reclassifies calls that already happened, so `calls` is
 *  invalidated alongside the directory itself. */
function invalidate(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({ queryKey: moduleKey('settings') })
  void client.invalidateQueries({ queryKey: moduleKey('calls') })
  void client.invalidateQueries({ queryKey: moduleKey('reports') })
}

export function useAddDirectoryEntry(): UseMutationResult<
  ReclassifyResponse,
  unknown,
  CreateDirectoryEntryRequest
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateDirectoryEntryRequest) =>
      api.post<ReclassifyResponse>('/line-directory', body),
    onSuccess: () => invalidate(client),
  })
}

export function useRemoveDirectoryEntry(): UseMutationResult<ReclassifyResponse, unknown, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (entryId: string) => api.delete<ReclassifyResponse>(`/line-directory/${entryId}`),
    onSuccess: () => invalidate(client),
  })
}

/**
 * What a rule will actually match, spelled out.
 *
 * The pattern is digits and the kind decides how they are compared — UC-25's
 * `*700` is the SUFFIX rule `700`, which is not obvious from either field on
 * its own. Showing the shape beside the input is the same idea as the
 * enrolment code's "8 characters": it lets somebody see that they have typed
 * the wrong thing without having to know the rule.
 */
export function ruleExample(kind: DirectoryRuleKind, pattern: string): string {
  const digits = pattern.replace(/\D/g, '') || '700'
  switch (kind) {
    case 'exact':
      return digits
    case 'prefix':
      return `${digits}…`
    case 'suffix':
      return `…${digits}`
  }
}
