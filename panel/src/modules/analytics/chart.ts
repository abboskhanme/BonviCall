/**
 * The arithmetic and the colours the analytics charts are drawn from — pure,
 * so it is tested without rendering anything.
 *
 * Same split as `modules/dashboard/chart.ts`: a chart component is declarative
 * and hard to assert on, and everything that could be *wrong* about it is a
 * function over data. That is what `__tests__/chart.test.ts` covers.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Colour comes from the CSS tokens and never from a hex literal**
 * (CONVENTIONS-CLIENT.md §3, §11). Recharts takes colour as a prop rather than
 * as a class, so the value handed to it is the token expression itself —
 * `hsl(var(--accent))`, resolved by the browser against `src/index.css`. That
 * is what makes the charts follow light, dark and system themes without a
 * `dark:` variant and without this file knowing which theme is on.
 *
 * `hsl(var(--x))` inside an SVG presentation attribute is the same mechanism
 * BonviZvonki's dashboard has shipped on for months; the tokens there and here
 * are both bare HSL triples for exactly this reason.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import type { BlockScore, ScoreBucket, TimeseriesPoint } from './api'

/** Every colour the charts use, named by what it MEANS rather than by hue. */
export const CHART_COLOR = {
  accent: 'hsl(var(--accent))',
  good: 'hsl(var(--good))',
  warn: 'hsl(var(--warn))',
  bad: 'hsl(var(--bad))',
  muted: 'hsl(var(--muted))',
  border: 'hsl(var(--border))',
  surface2: 'hsl(var(--surface-2))',
} as const

export type ChartColor = (typeof CHART_COLOR)[keyof typeof CHART_COLOR]

/**
 * A `Decimal` from the server, as a number a chart can scale.
 *
 * Every rate and average on this wire is NUMERIC and therefore arrives as a
 * string (`"78.3"`), which is the right decision server-side — it is the type
 * PostgreSQL computed it in, and a float would serialise as 78.30000000000001
 * often enough to be noticed. A chart axis needs a number, so the conversion
 * happens here, once, instead of in four components.
 *
 * `null` in, `null` out: a period with nothing scored is a **gap in the line**,
 * not a zero. Plotting it as 0 would drag a trend down through a quiet day.
 */
export function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** The same conversion where the absence of a value means zero — a count. */
export function toCount(value: string | null | undefined): number {
  return toNumber(value) ?? 0
}

/**
 * The four score bands, as `modules/analysis/labels.ts` defines them.
 *
 * Imported rather than re-stated: that file already mirrors
 * `analysis/entities.py::ScoreSummary.grade` and has a test pinning all four
 * boundaries. A second copy of three numbers is how a bar ends up one colour on
 * the list page and another on the chart.
 */
export { bandOf } from '@/modules/analysis/labels'

/**
 * The colour of a ten-point band in the histogram.
 *
 * Takes the band's floor, so 90-100 and 85-89 are asked the same question the
 * list page asks about a single score.
 */
export function bucketColor(floor: number): ChartColor {
  if (floor >= 85) return CHART_COLOR.good
  if (floor >= 70) return CHART_COLOR.accent
  if (floor >= 55) return CHART_COLOR.warn
  return CHART_COLOR.bad
}

/** `{floor: 80, ceiling: 89}` -> `"80–89"`. An en dash, as a range takes. */
export function bucketLabel(bucket: Pick<ScoreBucket, 'floor' | 'ceiling'>): string {
  return `${bucket.floor}–${bucket.ceiling}`
}

/** One row of the trend chart: the axis label, the count and the score. */
export interface TrendRow {
  label: string
  period_start: string
  calls: number
  ai_score: number | null
}

/**
 * `dd/mm` for a daily or weekly bucket, `mm/yyyy` for a monthly one.
 *
 * Built from the ISO string rather than from a `Date`: `period_start` is an
 * Asia/Tashkent calendar date the server already decided, and turning it into a
 * `Date` would re-interpret it in the reader's zone and move a January bucket
 * into December for anybody west of us.
 */
export function periodLabel(periodStart: string, bucket: string): string {
  const [year, month, day] = periodStart.split('-')
  if (!year || !month || !day) return periodStart
  return bucket === 'month' ? `${month}/${year}` : `${day}/${month}`
}

/** The trend response as chart rows, with the Decimal strings converted once. */
export function trendRows(points: readonly TimeseriesPoint[], bucket: string): TrendRow[] {
  return points.map((point) => ({
    label: periodLabel(point.period_start, bucket),
    period_start: point.period_start,
    calls: point.calls,
    ai_score: toNumber(point.ai_score),
  }))
}

/** One axis of the radar chart. */
export interface BlockRow {
  block: string
  label: string
  percent: number
  score: number
  max: number
}

/**
 * The block breakdown as radar rows.
 *
 * `percent` is what the radar plots, because the four blocks have their own
 * maxima and plotting raw points would draw a shape about the rubric's weights
 * rather than about the work. The points are kept for the tooltip.
 */
export function blockRows(
  blocks: readonly BlockScore[],
  label: (key: string) => string,
): BlockRow[] {
  return blocks.map((block) => ({
    block: block.block,
    label: label(block.block),
    percent: toCount(block.percent),
    score: toCount(block.score),
    max: block.max,
  }))
}

/**
 * Whether a delta should be read as good news.
 *
 * Ported from their `KpiCard`: more calls is good, more breaches is not, so the
 * card that counts breaches passes `invert`. Without it the red-flag card turns
 * green on the week somebody shouted at four customers.
 */
export function deltaIsGood(delta: number | null, invert = false): boolean | null {
  if (delta === null || delta === 0) return null
  const rising = delta > 0
  return invert ? !rising : rising
}
