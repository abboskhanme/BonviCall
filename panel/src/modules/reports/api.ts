/**
 * Reports — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * The gap report's totals must reconcile exactly with `/calls?has_audio=false`
 * for the same filter (UC-23), because the same filter builder produces both.
 * Nothing here recomputes anything the server already counted.
 */
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type GapReport = components['schemas']['GapReportResponse']
export type GapByReason = components['schemas']['GapByReasonOut']
export type GapByModel = components['schemas']['GapByModelOut']
export type GapByAgent = components['schemas']['GapByAgentOut']
export type OpenDelta = components['schemas']['OpenDeltaOut']
export type GapQuery = NonNullable<
  operations['gap_report_api_v1_reports_gap_get']['parameters']['query']
>

export function useGapReport(params: GapQuery): UseQueryResult<GapReport> {
  return useQuery({
    queryKey: queryKey('reports', 'gap', params),
    queryFn: () => api.get<GapReport>('/reports/gap', { ...params }),
  })
}

/**
 * A percentage the server computed, as a number.
 *
 * The wire carries these as decimal STRINGS — `"82.40"` — because the column
 * is NUMERIC and never a float (SPEC §3.0). Parsing here is only for
 * comparison and bar widths; the string is what gets displayed, so a value is
 * never re-rounded on its way to the screen and the report cannot disagree
 * with itself by a tenth of a point.
 */
export function percentValue(raw: string | null | undefined): number | null {
  if (raw === null || raw === undefined) return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

export type StorageReport = components['schemas']['StorageReportResponse']
export type StoragePoint = components['schemas']['StoragePointOut']
export type DataUsage = components['schemas']['DataUsageResponse']
export type DataUsageRow = components['schemas']['DataUsageRowOut']

/**
 * The disk the deployment is provisioned for (N18).
 *
 * A panel constant rather than a server value because nothing in
 * `app_settings` carries it — the provision is an infrastructure fact, not a
 * threshold the product enforces. It is here so the projection has something
 * to be a proportion OF: "10 GB in a year" means nothing on its own and
 * everything against a 250 GB disk.
 *
 * If the deployment is resized this number moves, and a setting would be the
 * better home for it.
 */
export const STORAGE_PROVISION_BYTES = 250 * 1024 ** 3

export function useStorageReport(): UseQueryResult<StorageReport> {
  return useQuery({
    queryKey: queryKey('reports', 'storage'),
    queryFn: () => api.get<StorageReport>('/reports/storage'),
  })
}

export function useDataUsage(): UseQueryResult<DataUsage> {
  return useQuery({
    queryKey: queryKey('reports', 'dataUsage'),
    queryFn: () => api.get<DataUsage>('/reports/data-usage'),
  })
}

/**
 * How full the disk would be at the projected rate, as a fraction.
 *
 * Clamped at 1 for the bar's width only — the CAPTION still says how far past
 * the provision the projection goes, because a bar pinned at 100% and a bar
 * pinned at 100% of three times the disk look identical and are not.
 */
export function provisionFraction(projectedBytes: number): number {
  return Math.min(1, projectedBytes / STORAGE_PROVISION_BYTES)
}
