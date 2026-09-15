/**
 * The geometry behind the dashboard's call-flow chart — arithmetic only, no
 * JSX (CONVENTIONS-CLIENT.md §1's rule for a module's non-component half).
 *
 * It is a separate file because every off-by-one a chart can have lives here:
 * a line drawn one bucket to the left, a y-axis whose top tick is below the
 * tallest point, a label stride that renders thirty dates on top of each
 * other. Those are testable as numbers and unreadable as a screenshot.
 *
 * The chart is drawn in PIXELS measured from the card, not in a `viewBox` that
 * is scaled to fit: a stretched `viewBox` distorts the text and the stroke
 * widths with it, and this card is 380px wide on a phone and 1600px on the
 * TV-sized screens the layout allows (SPEC §5.2).
 */
import { t } from '@/shared/i18n'
import type { CallStatsBucket } from '@/modules/calls/api'

/** The plot box. Room on the left for y labels, below for dates. */
export const CHART = {
  height: 220,
  padTop: 12,
  padRight: 14,
  padBottom: 24,
  padLeft: 38,
  /** Below this the card is too narrow to draw anything honest. */
  minWidth: 280,
} as const

export function plotWidth(width: number): number {
  return Math.max(width, CHART.minWidth) - CHART.padLeft - CHART.padRight
}

export function plotHeight(): number {
  return CHART.height - CHART.padTop - CHART.padBottom
}

/**
 * The step between gridlines, chosen so that **four of them reach the top**
 * and every one lands on a whole number.
 *
 * The four-step ladder is what keeps the axis readable: a top computed as
 * "the tallest point, rounded up" gives labels like 0, 4, 8, 11, 15, and a
 * reader who cannot add up the gridlines cannot read a value off the chart.
 * Counts are whole calls, so a fractional tick would be a lie about the data.
 */
const TICK_STEPS = [1, 2, 2.5, 3, 4, 5, 6, 8] as const

export function tickStep(max: number): number {
  if (!Number.isFinite(max) || max <= 4) return 1
  for (let power = 0; power < 12; power += 1) {
    const magnitude = 10 ** power
    for (const step of TICK_STEPS) {
      const candidate = step * magnitude
      if (candidate * 4 >= max && Number.isInteger(candidate)) return candidate
    }
  }
  return Math.ceil(max / 4)
}

/**
 * The top of the y-axis. Never the maximum itself — that puts the tallest
 * point exactly on the frame — and never zero: an empty period still needs an
 * axis, or every line collapses onto the baseline and a quiet week looks like
 * a broken chart.
 */
export function niceMax(max: number): number {
  return tickStep(max) * 4
}

/** Five gridlines, bottom to top, the last one exactly `max`. */
export function yTicks(max: number): number[] {
  const step = max / 4
  return [0, 1, 2, 3, 4].map((index) => Math.round(step * index))
}

/** The x of bucket `index`. A single bucket sits in the middle, not at the edge. */
export function xAt(index: number, count: number, width: number): number {
  const inner = plotWidth(width)
  if (count <= 1) return CHART.padLeft + inner / 2
  return CHART.padLeft + (inner * index) / (count - 1)
}

export function yAt(value: number, max: number): number {
  const safeMax = max > 0 ? max : 1
  return CHART.padTop + plotHeight() * (1 - Math.min(value, safeMax) / safeMax)
}

/**
 * One series as an SVG path.
 *
 * A single bucket gets a short horizontal dash rather than a `M` with nowhere
 * to go: a path of one point draws nothing at all, and "nothing" is what an
 * empty period already looks like.
 */
export function linePath(values: readonly number[], max: number, width: number): string {
  if (values.length === 0) return ''
  if (values.length === 1) {
    const y = yAt(values[0] ?? 0, max)
    const x = xAt(0, 1, width)
    return `M ${x - 8} ${y} L ${x + 8} ${y}`
  }
  return values
    .map((value, index) => {
      const command = index === 0 ? 'M' : 'L'
      return `${command} ${round(xAt(index, values.length, width))} ${round(yAt(value, max))}`
    })
    .join(' ')
}

function round(value: number): number {
  return Math.round(value * 10) / 10
}

/**
 * Which bucket the pointer is over.
 *
 * Nearest by x rather than "inside a band": a chart people read by sliding
 * along it must never have a dead pixel between two points.
 */
export function nearestIndex(offsetX: number, count: number, width: number): number {
  if (count <= 1) return 0
  const inner = plotWidth(width)
  const ratio = (offsetX - CHART.padLeft) / (inner || 1)
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))))
}

/**
 * How many x labels to skip so they do not overlap.
 *
 * Derived from the width rather than fixed, because thirty daily labels fit on
 * a 1600px board and collide at 380px. ~54px per label is the measured width
 * of `15.09` in this font plus breathing room.
 */
export function labelStride(count: number, width: number): number {
  const fits = Math.max(1, Math.floor(plotWidth(width) / 54))
  return Math.max(1, Math.ceil(count / fits))
}

/** `Yan` … `Dek` — the catalogue's twelve, never a locale's month name. */
export function monthShort(month: number): string {
  const key = `common.monthShort.${month}` as Parameters<typeof t>[0]
  return t(key)
}

/**
 * The pieces of a `YYYY-MM-DD` the server sent.
 *
 * Split from the string's own characters and never parsed into a `Date`: these
 * are Asia/Tashkent calendar dates (D-10), and `new Date('2026-09-15')` is
 * midnight UTC — which renders as the 14th for every reader west of Tashkent.
 */
function parts(iso: string): { year: string; month: string; day: string } {
  const [year = '', month = '', day = ''] = iso.split('-')
  return { year, month, day }
}

/** `15.09.2026` — one calendar date, as the rest of the panel writes them. */
export function isoDateLabel(iso: string): string {
  const { year, month, day } = parts(iso)
  return `${day}.${month}.${year}`
}

/** The label under one bucket: `15.09` for a day, `Sen` for a month. */
export function bucketLabel(bucket: CallStatsBucket, granularity: 'day' | 'month'): string {
  const { year, month, day } = parts(bucket.date_from)
  if (granularity === 'month') {
    // January carries its year: it is the only point where the reader needs to
    // be told the axis has rolled over.
    return month === '01' ? `${monthShort(1)} ${year}` : monthShort(Number(month))
  }
  return `${day}.${month}`
}

/** `15.09.2026` or `Sen 2026` — the readout above the chart. */
export function bucketTitle(bucket: CallStatsBucket, granularity: 'day' | 'month'): string {
  const { year, month } = parts(bucket.date_from)
  if (granularity === 'month') return `${monthShort(Number(month))} ${year}`
  return isoDateLabel(bucket.date_from)
}
