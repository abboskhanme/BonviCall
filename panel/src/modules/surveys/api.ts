/**
 * Customer ratings — TanStack Query hooks and nothing else
 * (CONVENTIONS-CLIENT.md §1).
 *
 * **Module mapping**: the panel's `surveys` module and its `groups` module
 * both read the server's single `surveys` module
 * (`server/src/api/panel/surveys.py` and `.../groups.py`). §1 requires the
 * mismatch to be written down here, so: the server merged the two because a
 * group exists in order to be surveyed and the tables reference each other;
 * the panel keeps them apart because they are two pages a different person
 * opens for a different reason.
 *
 * Read-only. The only thing that creates a rating is a customer answering in
 * Telegram, so this module owns no mutation and nothing invalidates its key.
 *
 * ⚠️ **The red-flag labels are never held here.** They come from
 * `GET /surveys/red-flags`, so a criterion added on the server appears without
 * a panel deploy. A hard-coded copy would also silently mislabel historical
 * answers the day the server's list changed.
 */
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { ApiError } from '@/shared/api/errors'
import { queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type Feedback = components['schemas']['FeedbackResponse']
export type FeedbackItem = components['schemas']['FeedbackItem']
export type RedFlagOption = components['schemas']['RedFlagOption']

/** The query string `GET /api/v1/surveys` accepts, from the contract. */
export type FeedbackQuery = NonNullable<
  operations['feedback_api_v1_surveys_get']['parameters']['query']
>

/**
 * The one-click windows.
 *
 * They start at 7 and not at 1, unlike the activity report's. A group is asked
 * at most once every fourteen days, so a one-day window over this fleet is
 * routinely empty and a page that opens on it reads as broken. 90 is the
 * default for the same reason.
 */
export const PERIODS = [7, 30, 90, 365] as const
export type Period = (typeof PERIODS)[number]

export const PERIOD_LABEL: Record<
  Period,
  'surveys.period.d7' | 'surveys.period.d30' | 'surveys.period.d90' | 'surveys.period.d365'
> = {
  7: 'surveys.period.d7',
  30: 'surveys.period.d30',
  90: 'surveys.period.d90',
  365: 'surveys.period.d365',
}

export const DEFAULT_PERIOD: Period = 90

function toQuery(params: FeedbackQuery): Query {
  return { ...params }
}

/**
 * The ratings for one window.
 *
 * `retry: false` because the meaningful failure here is a 403 — an admin has
 * closed the section to this salesperson — and asking again three times
 * changes nothing except how long they wait to be told.
 */
export function useFeedback(params: FeedbackQuery): UseQueryResult<Feedback> {
  return useQuery({
    queryKey: queryKey('surveys', 'feedback', params),
    queryFn: () => api.get<Feedback>('/surveys', toQuery(params)),
    retry: false,
    staleTime: 60_000,
  })
}

/**
 * The misconduct registry. The server owns it; this is a lookup over it.
 *
 * Half an hour of `staleTime`: it is effectively static, and a criterion added
 * during a session can wait that long to appear.
 */
export function useRedFlagOptions(): UseQueryResult<RedFlagOption[]> {
  return useQuery({
    queryKey: queryKey('surveys', 'red-flags'),
    queryFn: () => api.get<RedFlagOption[]>('/surveys/red-flags'),
    staleTime: 30 * 60_000,
    retry: false,
  })
}

/**
 * key → label. A key whose label has not arrived yet renders as the key.
 *
 * Deliberately not an empty string: an English identifier on screen is
 * unmistakable in review, and a chip that vanishes is not.
 */
export function useRedFlagLabels(): (key: string) => string {
  const options = useRedFlagOptions()
  const labels = new Map((options.data ?? []).map((option) => [option.key, option.label]))
  return (key: string) => labels.get(key) ?? key
}

/** Whether the section is closed to this caller by the access setting. */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}

/** How many more answers before the average opens. Null when already open. */
export function remaining(report: Feedback | undefined): number | null {
  if (!report || report.ready) return null
  return Math.max(0, report.min_responses - report.count)
}

/**
 * Star → tone, so the eye reads the row before the number.
 *
 * 4 and 5 are good, 3 is a warning, 1 and 2 are bad. The boundary at 3 is the
 * source's and is what the "low rating" filter uses too, so the colour and the
 * filter cannot disagree.
 */
export function csatTone(csat: number): 'good' | 'warn' | 'bad' {
  if (csat >= 4) return 'good'
  if (csat === 3) return 'warn'
  return 'bad'
}

export const LOW_CSAT_MAX = 3
