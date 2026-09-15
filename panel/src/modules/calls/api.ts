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
export type CallStats = components['schemas']['CallStatsResponse']
export type CallStatsBucket = components['schemas']['CallStatsBucket']
export type CallStatsPeriod = CallStats['period']
export type CallStatsQuery = NonNullable<
  operations['call_stats_api_v1_calls_stats_get']['parameters']['query']
>

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

/**
 * How many calls a page holds. Fixed, and not a control any more.
 *
 * The bar used to offer 50 / 100 / 500 / 1000 (SPEC §4.0 allows up to 1000 for
 * `/calls`). Nobody chose anything but the default, and the picker was one more
 * box in a filter bar that had too many — so the choice is gone and the value
 * is a constant. Paging is keyset, so reading further is "next page", not a
 * bigger number.
 */
export const PAGE_SIZE = 50

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

/**
 * The call flow over time — UC-11's five classes, per day or per month.
 *
 * The WINDOW is the server's arithmetic: this hook sends a period name, never
 * a pair of dates. A browser computing "a year ago" would do it in its own
 * timezone, and every business date in this product is an Asia/Tashkent
 * calendar date (D-10) — so the two would disagree for five hours a day and
 * nobody would be able to say which was right.
 *
 * Own-scope is not applied here either: the server narrows the same query the
 * list uses, so a salesperson's chart is their own calls (UC-21).
 */
export function useCallStats(params: CallStatsQuery): UseQueryResult<CallStats> {
  // `custom` is the only period that reads dates, and it needs BOTH: asking
  // with one of them would be a 400 fired on every keystroke of the second.
  const ready = params.period !== 'custom' || Boolean(params.date_from && params.date_to)
  return useQuery({
    queryKey: queryKey('calls', 'stats', { ...params }),
    queryFn: () => api.get<CallStats>('/calls/stats', { ...params }),
    placeholderData: keepPreviousData,
    enabled: ready,
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

/**
 * The recordings of **the page on screen**, as one ZIP.
 *
 * The opposite of the CSV export, and deliberately so: that one drops `limit`
 * and `cursor` because a spreadsheet of a filtered set has no pages, while
 * this one keeps them because the button sits under fifty rows and hands over
 * those fifty rows. A download whose contents do not match what the reader is
 * looking at is a download nobody can check.
 *
 * `with_total` still goes — a count is a list concern and the archive has no
 * use for one.
 */
export function callsAudioArchiveUrl(params: CallListQuery): string {
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
  search.delete('with_total')
  return `/api/v1/calls/audio-archive?${search.toString()}`
}
