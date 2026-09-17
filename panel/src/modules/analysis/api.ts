/**
 * Analysis — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `analysis` module reads the server's `analysis`
 * module (`server/src/api/panel/analysis.py`) **one to one**
 * (SPEC-ANALYTICS §7.2). There is no silent rename here, unlike the four
 * BonviZvonki inherited.
 *
 * Every type below comes from `types.gen.ts`; not one response shape is written
 * by hand (CONVENTIONS.md §1). `AnalysisListQuery` in particular is the
 * generated query-parameter type, so the filter bar can only offer filters the
 * server actually implements — `score_band` is the four band NAMES rather than
 * two numbers because the thresholds are the server's (§7.3).
 *
 * Query keys are `['analysis', 'list' | 'call' | 'queue', params]` and the run
 * mutation invalidates `['analysis']`, so queueing a call from the queue page
 * refreshes the stage counts, the failure list and that call's own page at once.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type AnalysisCallHeader = components['schemas']['AnalysisCallHeader']
export type AnalysisFailure = components['schemas']['AnalysisFailure']
export type AnalysisFailureRow = components['schemas']['AnalysisFailureRow']
export type AnalysisListItem = components['schemas']['AnalysisListItem']
export type AnalysisPage = components['schemas']['AnalysisListResponse']
export type AnalysisStage = components['schemas']['AnalysisStage']
export type AnalysisState = components['schemas']['AnalysisStateResponse']
export type AnalysisStatus = components['schemas']['AnalysisStatusResponse']
export type AnalysisMonth = components['schemas']['AnalysisMonthResponse']
export type CallAnalysis = components['schemas']['CallAnalysisResponse']
export type ProviderCooldown = components['schemas']['ProviderCooldownResponse']
export type RedFlag = components['schemas']['RedFlagOut']
export type Score = components['schemas']['ScoreResponse']
export type Transcript = components['schemas']['TranscriptResponse']
export type QueueCallRequest = components['schemas']['QueueCallRequest']

/** The query string `GET /api/v1/analysis/calls` accepts, from the contract. */
export type AnalysisListQuery = NonNullable<
  operations['list_analysed_calls_api_v1_analysis_calls_get']['parameters']['query']
>

/** `excellent | good | average | poor`, taken from the generated query type so
 *  the filter cannot offer a band the server would refuse with a 422. */
export type ScoreBand = NonNullable<NonNullable<AnalysisListQuery['score_band']>[number]>

/** One page of the scored-call list. Fifty, like `/calls` — keyset, so reading
 *  further is "next page" rather than a bigger number. */
export const PAGE_SIZE = 50

/**
 * How often a call that is still moving is re-read (§7.4).
 *
 * Ten seconds while `queued`/`transcribing`/`scoring`, and **nothing at all**
 * otherwise: a completed score never changes, and polling a finished page every
 * minute for the rest of the afternoon is a request per reader per minute for
 * an answer that is already on screen.
 */
export const POLL_RUNNING_MS = 10_000

/** The queue page is the operational one — it is opened to watch a backlog
 *  drain, so it refreshes faster than the 60 s default. */
export const POLL_QUEUE_MS = 15_000

/** The three stages that are still moving. `skipped` and `failed` are terminal
 *  until somebody or the nightly retry acts; `completed` is terminal full stop. */
const RUNNING_STAGES: readonly AnalysisStage[] = ['queued', 'transcribing', 'scoring']

export function isRunningStage(stage: AnalysisStage | null | undefined): boolean {
  return stage !== null && stage !== undefined && RUNNING_STAGES.includes(stage)
}

/**
 * A generated query object as `client.ts` wants it.
 *
 * The spread is what makes this safe: every value in `AnalysisListQuery` is a
 * string, number, boolean, array of strings, null or undefined, and `buildUrl`
 * drops the empty ones and repeats the arrays. No cast, so a filter of an
 * unsupported type would fail to compile here rather than on the wire.
 */
function toQuery(params: AnalysisListQuery): Query {
  return { ...params }
}

/**
 * One keyset page of analysed calls, newest conversation first (§7.3).
 *
 * `keepPreviousData` so paging does not flash the skeleton, exactly as the
 * calls list does it. The sort is the server's and fixed: there is one ordering
 * a reader of this page wants, and a sort control that can disagree with the
 * cursor is a way to lose rows.
 */
export function useAnalysisPage(params: AnalysisListQuery): UseQueryResult<AnalysisPage> {
  return useQuery({
    queryKey: queryKey('analysis', 'list', params),
    queryFn: () => api.get<AnalysisPage>('/analysis/calls', toQuery(params)),
    placeholderData: keepPreviousData,
  })
}

/**
 * One call's analysis: the flag, the call's own facts, the state, the
 * transcript and the score — in **one** request (§6.2).
 *
 * `enabled` travels in this response on purpose. Asking `/analysis/status` as
 * well, just to learn whether the feature exists, would be two round trips for
 * a boolean on every page load.
 *
 * A call the pipeline has never touched answers 200 with all three null, not
 * 404: the page must tell "not analysed" from "no such call". A call belonging
 * to another agent is the 404, decided by `CallService.get` and not re-derived
 * here (CONVENTIONS.md §11).
 */
export function useCallAnalysis(callId: string | undefined): UseQueryResult<CallAnalysis> {
  return useQuery({
    queryKey: queryKey('analysis', 'call', { callId }),
    queryFn: () => api.get<CallAnalysis>(`/analysis/calls/${callId}`),
    enabled: Boolean(callId),
    // Polls while the pipeline still has work to do on this call, and stops the
    // moment it does not. Reading the cached row rather than a render-time flag
    // keeps the decision inside the query, where the answer actually lives.
    refetchInterval: (query) =>
      isRunningStage(query.state.data?.state?.stage) ? POLL_RUNNING_MS : false,
  })
}

/** What is waiting, what broke and what the month has cost (§7.5). */
export function useAnalysisStatus(): UseQueryResult<AnalysisStatus> {
  return useQuery({
    queryKey: queryKey('analysis', 'queue'),
    queryFn: () => api.get<AnalysisStatus>('/analysis/status'),
    refetchInterval: POLL_QUEUE_MS,
  })
}

/**
 * `POST /analysis/calls/{id}` — queue one call. `analysis:run` only.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **The panel never sends `force: true`.** That flag clears the existing
 * transcript and score so both are recomputed, and it is the only way to spend
 * money twice on one call (§6.2). §7.4 offers a button in exactly two states —
 * a call that was never analysed, and one that failed — and neither of them has
 * anything to discard. A "re-score" control is a phase-2 conversation with the
 * client, not a side effect of this work.
 *
 * Returns the state row whether it was created or already there, so a re-press
 * is indistinguishable from the first press. The four ways it answers 409 are
 * the server's, and `messageForError` already carries an Uzbek sentence for
 * each (`errors.analysis_disabled` and friends).
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function useQueueAnalysis(): UseMutationResult<AnalysisState, unknown, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (callId: string) => {
      const body: QueueCallRequest = { force: false }
      return api.post<AnalysisState>(`/analysis/calls/${callId}`, body)
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('analysis') })
    },
  })
}
