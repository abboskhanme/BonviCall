/**
 * Calls — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `calls` module reads the server's `calls` module
 * (`server/src/api/panel/calls.py`) one to one. The agent filter's option list
 * comes from `modules/agents/api.ts::useAgentDirectory`; the ROW's agent name
 * does not, because `CallResponse.agent_name` is resolved server-side.
 *
 * Every type here comes from `types.gen.ts`; not one response shape is written
 * by hand (CONVENTIONS.md §1). `CallListQuery` in particular is the generated
 * query-parameter type, so the filters the server actually supports are a
 * compile-time fact rather than a guess — the day `direction` or `date_from`
 * lands on the server, `make types` makes it available here and nowhere else
 * needs editing.
 */
import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type Call = components['schemas']['CallResponse']
export type CallPage = components['schemas']['CallListResponse']
export type UpdateCallNoteRequest = components['schemas']['UpdateCallNoteRequest']

/**
 * The query string `GET /api/v1/calls` accepts, generated from the contract.
 *
 * SPEC §4.7 specifies a longer filter list; what the server implements today is
 * this. Taking the type from the contract rather than from the SPEC means the
 * page can only offer filters that exist, instead of sending parameters the
 * server silently ignores.
 */
export type CallListQuery = NonNullable<
  operations['list_calls_api_v1_calls_get']['parameters']['query']
>

/** SPEC §4.0: `limit` default 50, and 1000 for `/calls` because UC-19 renders 1000. */
export const DEFAULT_PAGE_SIZE = 50
export const MAX_PAGE_SIZE = 1000
export const PAGE_SIZES: readonly number[] = [50, 100, 500, MAX_PAGE_SIZE]

/**
 * A generated query object as `client.ts` wants it.
 *
 * The spread is what makes this safe: every value in `CallListQuery` is a
 * string, number, boolean, null or undefined, and `buildUrl` drops the last
 * three. No cast, so adding a filter of an unsupported type would fail here.
 */
function toQuery(params: CallListQuery): Query {
  return { ...params }
}

/**
 * One keyset page of calls.
 *
 * **Keyset, not offset** (SPEC §4.0): the page after this one is requested with
 * the opaque `next_cursor` this response returned, never with an offset. With
 * calls arriving while somebody pages, an OFFSET shifts every later page by one
 * and rows are silently skipped or repeated — which is precisely what UC-19
 * forbids.
 *
 * `keepPreviousData` so paging does not flash the skeleton (SPEC §5.3).
 * Own-scope is NOT applied here: `CallService.list()` narrows the query for a
 * `sales` caller, and a second copy of that rule in the panel would be a rule
 * that drifts (CONVENTIONS-CLIENT.md §2).
 */
export function useCallsPage(params: CallListQuery): UseQueryResult<CallPage> {
  return useQuery({
    queryKey: queryKey('calls', 'list', params),
    queryFn: () => api.get<CallPage>('/calls', toQuery(params)),
    placeholderData: keepPreviousData,
  })
}

/** One call. A call belonging to another agent answers 404, not 403 (UC-21). */
export function useCall(callId: string | undefined): UseQueryResult<Call> {
  return useQuery({
    queryKey: queryKey('calls', 'detail', { callId }),
    queryFn: () => api.get<Call>(`/calls/${callId}`),
    enabled: Boolean(callId),
  })
}

/**
 * `PATCH /calls/{id}` — the note and nothing else; every other field is the
 * device's. Invalidates the whole module so the list and the card agree.
 */
export function useUpdateCallNote(
  callId: string,
): UseMutationResult<Call, unknown, string | null> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (note: string | null) => {
      const body: UpdateCallNoteRequest = { note }
      return api.patch<Call>(`/calls/${callId}`, body)
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('calls') })
    },
  })
}

/**
 * The CSV export, streamed with the SAME filters the list is showing.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * UC-22: the row count must equal the `total` on screen, and it does because
 * the server re-runs the same filter builder rather than a parallel one. So
 * the panel's job is only to send the filters it is already displaying — and
 * to say what is about to be exported BEFORE the file arrives, because a
 * download is the one action with no undo and no preview.
 *
 * It goes through `fetch` in `audio.ts`'s sibling role rather than `api.get`:
 * the response is a stream with a `Content-Disposition` to read, not JSON.
 * The filename comes from the server for the reason SPEC §4.8 gives — two
 * naming rules in two places drift.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function callsExportUrl(params: CallListQuery): string {
  // Reuse the list's own query serialisation so a filter cannot be spelled one
  // way for the table and another for the file.
  const query = toQuery(params)
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item))
    } else {
      search.set(key, String(value))
    }
  }
  // `limit`, `cursor` and `with_total` are paging concerns and the export has
  // no pages; sending them would be noise at best.
  search.delete('limit')
  search.delete('cursor')
  search.delete('with_total')
  return `/api/v1/calls/export?${search.toString()}`
}
