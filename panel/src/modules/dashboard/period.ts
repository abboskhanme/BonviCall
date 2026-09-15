/**
 * The dashboard's one period control — hafta / oy / yil.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * It governs the whole page, not just the chart: the tiles that count calls
 * read the same window, so the headline number and the line under it can never
 * describe two different fortnights. The tiles that describe a fleet's state
 * RIGHT NOW — phones needing attention, open alerts — deliberately ignore it,
 * because "how many phones are silent last March" is not a question anybody
 * asks and a date filter over them would invent an answer.
 *
 * The value lives in the URL (CONVENTIONS-CLIENT.md §2) so a dashboard
 * somebody wants to show a colleague is a link, and the back button works.
 *
 * The WINDOW itself is never computed here. `/calls/stats` returns the dates
 * it aggregated, and everything on the page reads those: a browser working out
 * "a year ago" would do it in its own timezone, and every business date in this
 * product is an Asia/Tashkent calendar date (D-10).
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useSearchParams } from 'react-router-dom'

import { useCallStats, type CallStatsPeriod } from '@/modules/calls/api'
import type { MessageKey } from '@/shared/i18n'

export type DashboardPeriod = CallStatsPeriod

export const PERIODS: readonly DashboardPeriod[] = ['week', 'month', 'year', 'custom']

export const PERIOD_LABEL: Record<DashboardPeriod, MessageKey> = {
  week: 'dashboard.chart.period.week',
  month: 'dashboard.chart.period.month',
  year: 'dashboard.chart.period.year',
  custom: 'dashboard.chart.period.custom',
}

function isPeriod(value: string | null): value is DashboardPeriod {
  return value === 'week' || value === 'month' || value === 'year' || value === 'custom'
}

/** An ISO calendar date and nothing else — `?date_from=yesterday` is not one. */
function isCalendarDate(value: string | null): value is string {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value)
}

/** What the page is showing: a preset, or the reader's own two dates. */
export type PeriodSelection = {
  period: DashboardPeriod
  date_from?: string
  date_to?: string
}

/** A custom period needs both ends before anything can be asked for. */
export function isComplete(selection: PeriodSelection): boolean {
  return (
    selection.period !== 'custom' || Boolean(selection.date_from && selection.date_to)
  )
}

export interface PeriodControl {
  selection: PeriodSelection
  setPeriod: (next: DashboardPeriod) => void
  /** Move one end of a custom range. Setting either end selects `custom`. */
  setBound: (which: 'date_from' | 'date_to', value: string | null) => void
}

/**
 * `?period=`, plus `?date_from=`/`?date_to=` when it is `custom`. Default
 * `week` — the shortest window, so the first paint is the smallest question.
 *
 * `replace` on every setter: flipping between the windows is looking at one
 * page, not visiting four, and a reader who tried all of them should not have
 * to press Back four times to leave.
 */
export function useDashboardPeriod(): PeriodControl {
  const [params, setParams] = useSearchParams()
  const raw = params.get('period')
  const period: DashboardPeriod = isPeriod(raw) ? raw : 'week'
  const from = params.get('date_from')
  const to = params.get('date_to')

  const write = (mutate: (search: URLSearchParams) => void) => {
    const search = new URLSearchParams(params)
    mutate(search)
    setParams(search, { replace: true })
  }

  return {
    selection: {
      period,
      // The dates are read only for `custom`, exactly as the server reads
      // them: a preset that could carry dates is a link whose label lies.
      ...(period === 'custom' && isCalendarDate(from) ? { date_from: from } : {}),
      ...(period === 'custom' && isCalendarDate(to) ? { date_to: to } : {}),
    },
    setPeriod: (next) =>
      write((search) => {
        search.set('period', next)
        if (next !== 'custom') {
          // Left behind, they would reappear the next time somebody picked
          // `custom` — a window from a session nobody remembers.
          search.delete('date_from')
          search.delete('date_to')
        }
      }),
    setBound: (which, value) =>
      write((search) => {
        search.set('period', 'custom')
        if (value) search.set(which, value)
        else search.delete(which)
      }),
  }
}

/** The dates the server aggregated, for the tiles that filter by date. */
export interface PeriodWindow {
  date_from: string
  date_to: string
}

/**
 * The window, taken from the chart's own response.
 *
 * It shares `useCallStats`'s query key, so a tile asking for it costs no
 * second request — and, more to the point, cannot disagree with the chart
 * about which days the period covers.
 *
 * `undefined` while the request is in flight, and for a caller the server
 * refuses. A tile falls back to its unfiltered question rather than to a
 * guessed window: showing the wrong fortnight silently is worse than showing
 * all of time and saying so.
 */
export function usePeriodWindow(selection: PeriodSelection): PeriodWindow | undefined {
  const query = useCallStats(selection)
  // `keepPreviousData` is what stops the page flashing while a period changes,
  // and it is also why this checks completeness: the previous window's answer
  // is still in hand while a custom range is half-chosen, and showing it would
  // date a figure to a period nobody asked for.
  if (!isComplete(selection) || !query.data) return undefined
  return { date_from: query.data.date_from, date_to: query.data.date_to }
}
