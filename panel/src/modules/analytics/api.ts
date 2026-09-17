/**
 * Analytics — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `analytics` module reads the server's
 * `analytics` module (`server/src/api/panel/analytics.py`) **one to one**. It
 * is a sibling of the panel's `analysis` module, which reads one call at a
 * time; this one never reads a call at all, only aggregates over them.
 *
 * Ported from `../BonviZvonki/services/web/src/modules/analytics/api.ts`, which
 * hand-wrote nine response interfaces. Not one of them survives: every type
 * below comes from `types.gen.ts` (CONVENTIONS.md §1), so a renamed server
 * field is a compile error here instead of an `undefined` in a chart.
 *
 * **Six queries, one filter.** They share `['analytics', <slice>, params]` with
 * the same `params` object, so changing the window moves the whole page at once
 * and the KPI card cannot describe a different period from the chart under it —
 * which is the defect their `_scope_ratings` comment records (one screen
 * showing 4.18 in a card and 4.67 in the table beneath it).
 *
 * There is no mutation here: a report writes nothing, so nothing invalidates
 * `['analytics']`.
 */
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type AnalyticsOverview = components['schemas']['AnalyticsOverviewResponse']
export type AnalyticsTimeseries = components['schemas']['AnalyticsTimeseriesResponse']
export type AgentRanking = components['schemas']['AgentRankingResponse']
export type AgentRankRow = components['schemas']['AgentRankRowOut']
export type BlockBreakdown = components['schemas']['BlockBreakdownResponse']
export type BlockScore = components['schemas']['BlockScoreOut']
export type RedFlagBreakdown = components['schemas']['RedFlagBreakdownResponse']
export type RedFlagCount = components['schemas']['RedFlagCountOut']
export type ScoreDistribution = components['schemas']['ScoreDistributionResponse']
export type ScoreBucket = components['schemas']['ScoreBucketOut']
export type TimeseriesPoint = components['schemas']['TimeseriesPointOut']
export type CallTypeCounts = components['schemas']['CallTypeCountsOut']
export type CountMetric = components['schemas']['CountMetricOut']
export type ScoreMetric = components['schemas']['ScoreMetricOut']

/** The filter set every one of the six paths accepts, from the contract. */
export type AnalyticsQuery = NonNullable<
  operations['analytics_overview_api_v1_analytics_overview_get']['parameters']['query']
>

/** The same, plus the trend's own control. Separate rather than optional on
 *  `AnalyticsQuery`: `bucket` is not a filter, and the other five paths would
 *  answer 422 if it reached them. */
export type TimeseriesQuery = NonNullable<
  operations['analytics_timeseries_api_v1_analytics_timeseries_get']['parameters']['query']
>

/** `day | week | month`, taken from the generated query type so the control
 *  cannot offer a bucket the server would refuse with a 422. */
export type Bucket = NonNullable<TimeseriesQuery['bucket']>

/**
 * How long a report is considered fresh.
 *
 * A month of scores does not change while somebody reads it, and six requests
 * per focus change is six aggregate queries over the whole window. Long enough
 * to be quiet, short enough that a call scored during the meeting appears
 * without a reload.
 */
const STALE_MS = 60_000

/**
 * A generated query object as `client.ts` wants it.
 *
 * The spread is what makes this safe: every value in `AnalyticsQuery` is a
 * string, number, boolean, array of strings, null or undefined, and `buildUrl`
 * drops the empty ones and repeats the arrays. No cast, so a filter of an
 * unsupported type would fail to compile here rather than on the wire.
 */
function toQuery(params: AnalyticsQuery | TimeseriesQuery): Query {
  return { ...params }
}

function report<T>(
  slice: string,
  path: string,
  params: AnalyticsQuery | TimeseriesQuery,
) {
  return {
    queryKey: queryKey('analytics', slice, params),
    queryFn: () => api.get<T>(path, toQuery(params)),
    staleTime: STALE_MS,
  }
}

/** The KPI cards, each with its change against the previous equal window. */
export function useOverview(params: AnalyticsQuery): UseQueryResult<AnalyticsOverview> {
  return useQuery(report<AnalyticsOverview>('overview', '/analytics/overview', params))
}

/** The trend. `bucket` is part of the key: it is a different question, not a
 *  different rendering of the same answer. */
export function useTimeseries(
  params: AnalyticsQuery,
  bucket: Bucket,
): UseQueryResult<AnalyticsTimeseries> {
  return useQuery(
    report<AnalyticsTimeseries>('timeseries', '/analytics/timeseries', {
      ...params,
      bucket,
    }),
  )
}

/** The leaderboard. */
export function useAgentRanking(params: AnalyticsQuery): UseQueryResult<AgentRanking> {
  return useQuery(report<AgentRanking>('agents', '/analytics/agents', params))
}

/** The rubric blocks, for the radar chart. */
export function useBlockBreakdown(params: AnalyticsQuery): UseQueryResult<BlockBreakdown> {
  return useQuery(report<BlockBreakdown>('blocks', '/analytics/blocks', params))
}

/** The breaches, commonest first. */
export function useRedFlagBreakdown(
  params: AnalyticsQuery,
): UseQueryResult<RedFlagBreakdown> {
  return useQuery(report<RedFlagBreakdown>('red-flags', '/analytics/red-flags', params))
}

/** The score histogram — always ten bands, empty ones included. */
export function useScoreDistribution(
  params: AnalyticsQuery,
): UseQueryResult<ScoreDistribution> {
  return useQuery(report<ScoreDistribution>('distribution', '/analytics/distribution', params))
}
