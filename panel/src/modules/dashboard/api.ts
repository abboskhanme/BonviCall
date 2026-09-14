/**
 * The one report the dashboard still reads — TanStack Query hooks only
 * (CONVENTIONS-CLIENT.md §1).
 *
 * It lived in `modules/reports` until 2026-09-14, alongside the gap report
 * page and the storage page. Both pages were removed at the client's request
 * and the module went with them; this hook did not, because the capture rate
 * is the number the whole product is judged on (UC-23) and it still headlines
 * the dashboard. It moved here rather than keeping a module alive for one
 * function.
 *
 * The endpoint is untouched: the server still computes the report, and the
 * totals still reconcile exactly with `/calls?has_audio=false` for the same
 * filter, because the same filter builder produces both.
 */
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type GapReport = components['schemas']['GapReportResponse']
export type GapQuery = NonNullable<
  operations['gap_report_api_v1_reports_gap_get']['parameters']['query']
>

export function useGapReport(params: GapQuery): UseQueryResult<GapReport> {
  return useQuery({
    queryKey: queryKey('reports', 'gap', params),
    queryFn: () => api.get<GapReport>('/reports/gap', { ...params }),
  })
}
