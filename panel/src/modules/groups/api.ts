/**
 * Telegram groups — TanStack Query hooks and nothing else
 * (CONVENTIONS-CLIENT.md §1).
 *
 * **Module mapping, because it is not one to one** (§1 requires it written
 * here): the panel's `groups` and `surveys` modules both read the server's
 * single `surveys` module. The server merged them because a group exists in
 * order to be surveyed and the two tables reference each other; the panel
 * keeps them apart because they are two pages a different person opens.
 *
 * Every type comes from `types.gen.ts` (CONVENTIONS.md §1). Not one response
 * shape is written by hand — BonviZvonki hand-writes `TelegramGroup` with
 * fourteen snake_case fields and survives because one person writes both sides
 * the same day.
 *
 * ═══ SCALE IS THE DESIGN ═══════════════════════════════════════════════════
 * One group per customer, roughly a thousand of them. So there is deliberately
 * no "fetch every group" hook:
 *
 *   · `useGroupTree()` — one light aggregate, drawn without opening anything.
 *   · `useGroupPage()` — the leaves of ONE opened node, 50 at a time.
 *
 * A closed node costs zero requests.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { ApiError } from '@/shared/api/errors'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type Group = components['schemas']['GroupResponse']
export type GroupPage = components['schemas']['GroupPageResponse']
export type GroupTree = components['schemas']['GroupTreeResponse']
export type TreeAgent = components['schemas']['TreeAgentNode']
export type BroadcastResult = components['schemas']['BroadcastResponse']
export type BroadcastSkip = components['schemas']['BroadcastSkip']
export type Dispatch = components['schemas']['DispatchResponse']

/** Rows per leaf page. The server clamps anything larger. */
export const PAGE_SIZE = 50

/** The server's own bulk ceiling, so a larger selection is split here. */
export const BULK_CHUNK = 200

/** The key the unbound bucket is identified by in the page's local state. */
export const UNASSIGNED_KEY = '__unassigned__'

export interface GroupsQuery {
  /** Index signature so a query object is a `QueryParams` without a cast —
   *  TanStack Query hashes the key, and `Record<string, unknown>` is what it
   *  asks for. An `interface` without one is not assignable to it. */
  [key: string]: string | number | boolean | undefined
  agent_id?: string
  /** `false` returns ONLY the groups nobody is bound to. */
  has_agent?: boolean
  search?: string
  include_inactive?: boolean
  cursor?: string
  limit?: number
}

function toQuery(params: GroupsQuery): Query {
  return { ...params }
}

/**
 * The page's skeleton. One request, and it is the only one a closed page makes.
 *
 * The counts are always of ACTIVE groups and the endpoint takes no filter, so
 * the "show inactive too" switch changes the leaves and never the node counts.
 * That is deliberate: a node count keeps one meaning, "groups that are
 * working".
 */
export function useGroupTree(): UseQueryResult<GroupTree> {
  return useQuery({
    queryKey: queryKey('groups', 'tree'),
    queryFn: () => api.get<GroupTree>('/groups/tree'),
    staleTime: 30_000,
  })
}

/**
 * One leaf page.
 *
 * `enabled` is how a closed node costs nothing: the hook is mounted and issues
 * no request until its node is opened.
 *
 * `keepPreviousData` so paging does not blank the list — the rows stay put
 * while the next page is in flight, which is what makes the arrows feel like a
 * control rather than a reload.
 */
export function useGroupPage(params: GroupsQuery, enabled = true): UseQueryResult<GroupPage> {
  return useQuery({
    queryKey: queryKey('groups', 'page', params),
    queryFn: () => api.get<GroupPage>('/groups', toQuery({ limit: PAGE_SIZE, ...params })),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/**
 * Invalidate everything a group change can move.
 *
 * `groups` covers the tree and every leaf. `surveys` is NOT invalidated:
 * binding a group changes nothing about the ratings already collected, and
 * refetching them would re-run five aggregates to show identical numbers.
 */
function useInvalidateGroups(): () => void {
  const client = useQueryClient()
  return () => void client.invalidateQueries({ queryKey: moduleKey('groups') })
}

export interface GroupPatch {
  id: string
  agent_id?: string | null
  is_active?: boolean
}

export function useSaveGroup() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: ({ id, ...body }: GroupPatch) => api.patch<Group>(`/groups/${id}`, body),
    onSuccess: invalidate,
  })
}

export function useDeleteGroup() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/groups/${id}`),
    onSuccess: invalidate,
  })
}

export interface BulkFailure {
  /** The first group in the failed chunk, so an admin knows where it stopped. */
  title: string
  count: number
  message: string
}

export interface BulkResult {
  updated: number
  failed: BulkFailure[]
}

export interface BulkVars {
  groups: Group[]
  patch: { agent_id?: string | null; is_active?: boolean }
  onProgress?: (done: number, total: number) => void
}

/**
 * One change applied to many groups, in chunks of {@link BULK_CHUNK}.
 *
 * ⚠️ **A failed chunk does not cancel the rest, and every chunk is reported.**
 * If 400 groups are selected and the first 200 save while the second 200 fail,
 * an admin has to be told exactly that — not the single word "error", and not
 * a silent partial success they discover later by counting rows.
 */
export function useBulkPatchGroups() {
  const invalidate = useInvalidateGroups()

  return useMutation({
    mutationFn: async ({ groups, patch, onProgress }: BulkVars): Promise<BulkResult> => {
      const failed: BulkFailure[] = []
      let updated = 0
      let done = 0

      for (let start = 0; start < groups.length; start += BULK_CHUNK) {
        const chunk = groups.slice(start, start + BULK_CHUNK)
        try {
          const result = await api.patch<{ updated: number }>('/groups/bulk', {
            ...patch,
            group_ids: chunk.map((group) => group.id),
          })
          updated += result.updated
        } catch (error) {
          failed.push({
            title: chunk[0]?.title ?? '',
            count: chunk.length,
            message: error instanceof ApiError ? error.message : '',
          })
        } finally {
          done += chunk.length
          onProgress?.(done, groups.length)
        }
      }

      return { updated, failed }
    },
    onSuccess: invalidate,
  })
}

/**
 * Queue a survey for one group.
 *
 * Two of the 409s are ordinary states rather than faults — `group_not_bound`
 * and `survey_suppressed` — and the page renders the server's reason instead
 * of a red error.
 */
export function useSendSurvey() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) =>
      api.post<Dispatch>(`/groups/${id}/survey`, { force: force ?? false }),
    onSuccess: invalidate,
  })
}

/**
 * Queue a survey for every eligible group.
 *
 * `force: true` is the default and is the whole point of the button: when an
 * admin says "send to everyone now", silently doing nothing because of a
 * ten-day window is the broken behaviour.
 */
export function useBroadcastSurveys() {
  const invalidate = useInvalidateGroups()
  return useMutation({
    mutationFn: () => api.post<BroadcastResult>('/groups/surveys/broadcast', { force: true }),
    onSuccess: invalidate,
  })
}

/** Deleting is offered only once the bot is out of the chat — the server agrees. */
export function canDelete(group: Group): boolean {
  return group.bot_status === 'left' || group.bot_status === 'kicked'
}

/**
 * Whether the "send survey" button is live.
 *
 * Being unbound is deliberately NOT checked here. The server answers 409 with
 * `group_not_bound` and the page shows that sentence; a silently disabled
 * button tells the reader nothing about why.
 */
export function canSendSurvey(group: Group): boolean {
  return group.is_active && !canDelete(group)
}

/** A row an admin is holding by hand; automation does not touch it. */
export function isManual(group: Group): boolean {
  return group.bound_by === 'manual'
}

/** The machine reason out of a 409 envelope, for the ones that are not errors. */
export function conflictReason(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = error.detail as { reason?: string } | null
  return detail?.reason ?? null
}

/** Totals across the tree, so the tiles and the broadcast modal agree. */
export function treeTotals(tree: GroupTree | undefined) {
  if (!tree) return { groups: 0, responses: 0, unassigned: 0, bound: 0 }
  let groups = tree.unassigned.group_count
  let responses = tree.unassigned.response_count
  for (const agent of tree.agents) {
    groups += agent.group_count
    responses += agent.response_count
  }
  return {
    groups,
    responses,
    unassigned: tree.unassigned.group_count,
    bound: groups - tree.unassigned.group_count,
  }
}
