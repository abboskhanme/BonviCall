/**
 * The employee table's columns and its sort — the module's non-component half
 * (CONVENTIONS-CLIENT.md §1, the same split `modules/dashboard/chart.ts` uses).
 *
 * It is a separate file because every mistake this table can make is here and
 * all of them are testable as values rather than as a screenshot: a column that
 * sorts by a different field from the one it displays, an absent value treated
 * as zero, a cached array sorted in place.
 *
 * ⚠️ NAME, EXPLANATION AND SORT VALUE ARE ON ONE LINE, deliberately. Kept as
 * two lists they drift — a column is added, its explanation is forgotten, and
 * nothing says so. `value` is here for the same reason: whoever adds a column
 * sees on the same line that it has to be sortable too, and the sort cannot end
 * up reading a different field from the one on screen, which is the worst kind
 * of bug because nobody notices it.
 */
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount, formatDuration } from '@/shared/lib/format'

import type { ActivityRow } from './api'
import type { MessageKey } from '@/shared/i18n'
import { TONE_CLASS, medianTone, rateTone } from './series'

export interface Column {
  key: string
  label: MessageKey
  tip: MessageKey
  /** What the column sorts on. `null` means "no value", never zero. */
  value: (row: ActivityRow) => number | null
  render: (row: ActivityRow) => string
  tone?: (row: ActivityRow) => string
}

export const COLUMNS: readonly Column[] = [
  {
    key: 'out',
    label: 'activity.colOut',
    tip: 'activity.tipOut',
    value: (row) => row.outbound_total,
    render: (row) => formatCount(row.outbound_total),
  },
  {
    key: 'outNo',
    label: 'activity.colOutNoAnswer',
    tip: 'activity.tipOutNoAnswer',
    value: (row) => row.outbound_no_answer,
    render: (row) => formatCount(row.outbound_no_answer),
    tone: () => 'text-muted',
  },
  {
    key: 'in',
    label: 'activity.colIn',
    tip: 'activity.tipIn',
    value: (row) => row.inbound_total,
    render: (row) => formatCount(row.inbound_total),
  },
  {
    key: 'missed',
    label: 'activity.colMissed',
    tip: 'activity.tipMissed',
    value: (row) => row.missed,
    render: (row) => formatCount(row.missed),
    // Red only above zero: a red zero is a false alarm about a row that is fine.
    tone: (row) => (row.missed ? 'text-bad' : 'text-muted'),
  },
  {
    key: 'clients',
    label: 'activity.colClients',
    tip: 'activity.tipClients',
    value: (row) => row.missed_clients,
    render: (row) => formatCount(row.missed_clients),
    tone: () => 'text-muted',
  },
  {
    key: 'unreached',
    label: 'activity.colUnreached',
    tip: 'activity.tipUnreached',
    value: (row) => row.clients_unreached,
    render: (row) => formatCount(row.clients_unreached),
    // The manager's to-do list, so a non-zero has to stand out.
    tone: (row) => (row.clients_unreached ? 'font-semibold text-bad' : 'text-muted'),
  },
  {
    key: 'rate',
    label: 'activity.colRate',
    tip: 'activity.tipRate',
    value: (row) => row.callback_rate,
    render: (row) => (row.callback_rate === null ? EM_DASH : `${row.callback_rate}%`),
    tone: (row) => cn('font-semibold', TONE_CLASS[rateTone(row.callback_rate)]),
  },
  {
    key: 'median',
    label: 'activity.colMedian',
    tip: 'activity.tipMedian',
    value: (row) => row.callback_median_minutes,
    render: (row) =>
      row.callback_median_minutes === null ? EM_DASH : `${row.callback_median_minutes}`,
    /* ⚠️ Coloured INDEPENDENTLY of the rate: a high rate does not excuse being
       slow, and one colour for both would read as one measure. Measured — one
       team returned 89 % of calls with a 43-minute median. */
    tone: (row) => cn('font-medium', TONE_CLASS[medianTone(row.callback_median_minutes)]),
  },
  {
    key: 'talk',
    label: 'activity.colTalk',
    tip: 'activity.tipTalk',
    value: (row) => row.talk_seconds,
    render: (row) => formatDuration(row.talk_seconds),
    tone: () => 'text-muted',
  },
]

export type SortOrder = 'asc' | 'desc'

/**
 * Two employees by name.
 *
 * ⚠️ `localeCompare`, never `<`: the roster carries both Cyrillic and Latin
 * names and a byte comparison splits them into two separate blocks.
 * `sensitivity: 'base'` ignores case and accents; `numeric` puts "Sklad 2"
 * before "Sklad 10".
 */
export function byName(a: ActivityRow, b: ActivityRow): number {
  return a.agent_name.localeCompare(b.agent_name, undefined, {
    sensitivity: 'base',
    numeric: true,
  })
}

/**
 * The rows in the reader's order.
 *
 * ⚠️ On a COPY. `sort()` mutates in place and this array is TanStack Query's
 * cached object — sorting it directly corrupts the cache and another page gets
 * a different order.
 *
 * ⚠️ An absent value (an em dash) sorts LAST whichever way the arrow points.
 * Treated as zero, an employee with NO missed calls would climb to the top of
 * an ascending "worst first" list and read as the worst in the company — and
 * they have nothing to measure at all.
 */
export function sortRows(
  rows: readonly ActivityRow[],
  field: string | null,
  order: SortOrder,
): ActivityRow[] {
  if (field === null) return [...rows]
  const sign = order === 'asc' ? 1 : -1
  const column = COLUMNS.find((item) => item.key === field)
  return [...rows].sort((a, b) => {
    if (!column) return sign * byName(a, b)
    const left = column.value(a)
    const right = column.value(b)
    if (left === null || right === null) {
      if (left === right) return byName(a, b)
      return left === null ? 1 : -1
    }
    // Ties break by name, or equal rows swap places on every render.
    return left === right ? byName(a, b) : sign * (left - right)
  })
}
