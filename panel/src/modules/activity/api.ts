/**
 * Activity — TanStack Query hooks and nothing else (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `activity` module reads the server's `activity`
 * module (`server/src/api/panel/activity.py`) **one to one**. BonviZvonki hides
 * this behind a rename — its `activity` page calls `modules/analytics` — which
 * is one of the four silent mismatches §1 names; there is none here.
 *
 * Every type comes from `types.gen.ts`, generated from
 * `contract/openapi-panel-v1.json` by `make types`. Not one response shape is
 * written by hand (CONVENTIONS.md §1): a renamed server field must be a
 * compile error here, not a `NaN` in a spreadsheet somebody emails to a
 * manager.
 *
 * Access: `calls:read` or `calls:read:own`. A salesperson passes the gate and
 * the SERVER narrows the rows to their own agent; this module never
 * re-implements that rule, it only hides the agent filter, which is
 * presentation rather than access control (CONVENTIONS-CLIENT.md §2).
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type ActivityReport = components['schemas']['ActivityResponse']
export type ActivityRow = components['schemas']['AgentActivityRow']
export type ActivityDay = components['schemas']['ActivityDayRow']
export type ActivityHour = components['schemas']['ActivityHourRow']
export type MissedClientsReport = components['schemas']['MissedClientsResponse']
export type MissedClient = components['schemas']['MissedClientRow']

/** The query string `GET /api/v1/activity` accepts, from the contract. */
export type ActivityQuery = NonNullable<
  operations['activity_report_api_v1_activity_get']['parameters']['query']
>

/**
 * The four one-click windows, and they are the server's own list.
 *
 * "The manager asks for these four" is the whole justification, so they are a
 * constant rather than a setting. `1` matters more than it looks: it is what
 * switches the chart to an hourly cut, which is the most actionable view the
 * report has.
 */
export const PERIODS = [1, 7, 15, 30] as const
export type Period = (typeof PERIODS)[number]

/** The label key for a period button. Written out so Tailwind-style string
 *  building never reaches the message catalogue. */
export const PERIOD_LABEL: Record<Period, 'activity.period.d1' | 'activity.period.d7' | 'activity.period.d15' | 'activity.period.d30'> = {
  1: 'activity.period.d1',
  7: 'activity.period.d7',
  15: 'activity.period.d15',
  30: 'activity.period.d30',
}

/**
 * The window below which the chart switches from days to hours.
 *
 * Decided from the SERVER's `days`, not from the button that was pressed: an
 * explicit date range wins over `days` server-side, so the two can disagree and
 * the axis must follow the data that actually came back.
 */
export const HOURLY_BELOW_DAYS = 1

/** A generated query object as `client.ts` wants it. The spread is what keeps
 *  this safe — every value is a string, number, array or undefined, and
 *  `buildUrl` drops the empty ones and repeats the arrays. No cast. */
function toQuery(params: ActivityQuery): Query {
  return { ...params }
}

/**
 * The report for one window.
 *
 * `keepPreviousData` so switching period does not blank the page: the numbers
 * on screen stay put for the moment the next window is in flight, which is what
 * makes the four buttons feel like a control rather than a reload.
 *
 * A minute of `staleTime`: this is a report over a window that ends today, and
 * refetching it on every focus change would re-run six aggregates for an answer
 * that cannot have moved.
 */
export function useActivity(params: ActivityQuery): UseQueryResult<ActivityReport> {
  return useQuery({
    queryKey: queryKey('activity', 'report', params),
    queryFn: () => api.get<ActivityReport>('/activity', toQuery(params)),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })
}

/**
 * One employee's unreached customers — the detail that PROVES the number.
 *
 * ⚠️ It is asked with the SAME window the report was asked with. If the two
 * windows drift, "9 in the table, 8 in the list" is what a manager sees, and
 * the tool built to make a figure believable is what makes it doubtful.
 *
 * Disabled until a row is picked, so opening the page issues one request rather
 * than one per employee.
 */
export function useMissedClients(
  agentId: string | null,
  params: ActivityQuery,
): UseQueryResult<MissedClientsReport> {
  return useQuery({
    queryKey: queryKey('activity', 'missed-clients', { ...params, agentId }),
    queryFn: () =>
      api.get<MissedClientsReport>('/activity/missed-clients', {
        ...toQuery(params),
        agent_id: agentId,
      }),
    enabled: Boolean(agentId),
    staleTime: 60_000,
  })
}
