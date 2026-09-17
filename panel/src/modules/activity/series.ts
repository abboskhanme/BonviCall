/**
 * The chart's four series, and the thresholds that colour a number — ONE list,
 * read by the SCREEN and by the EXPORTED FILE.
 *
 * Ported from BonviZvonki `web/src/modules/activity/series.ts`, with its
 * reason intact: the colours used to be written twice — through a CSS token on
 * screen and as a hand-copied hex in the Excel file — and two copies drift
 * without anybody noticing. Change the theme and the file keeps the old
 * colour, and the reader asks "which line is this?".
 *
 * ⚠️ BOTH THE TOKEN AND THE HEX ARE NEEDED, because they are used in places
 * that cannot share one value. On screen the colour follows the theme
 * (`stroke-accent` resolves to `hsl(var(--accent))`, which is a different
 * colour in dark mode). The PNG that goes into the spreadsheet has no theme at
 * all: it is always drawn on white and a canvas wants a literal.
 *
 * **The hex values are this product's own light-theme tokens**, read off
 * `src/index.css` and converted: `--accent: 208 62% 34%` is `#215A8C`,
 * `--good: 152 62% 31%` is `#1E8052`, `--warn: 30 95% 36%` is `#B35C05`,
 * `--bad: 352 74% 46%` is `#CC1E36`. Three of the four are byte-identical to
 * BonviZvonki's copy, which is how the two palettes were confirmed to be the
 * same one rather than two that happen to look alike.
 *
 * The **thresholds** live here for the same reason the colours do. Their code
 * carries them twice — `callbackTone()` returns a Tailwind class, `rateColor()`
 * returns a hex — with a comment admitting that only the numbers are shared.
 * Here the numbers are shared and each side keeps its own rendering.
 */

/** A series key, and therefore a field on both `ActivityDayRow` and `ActivityHourRow`. */
export type SeriesKey = 'inbound' | 'outbound' | 'missed' | 'outbound_no_answer'

/** A semantic token. The Tailwind class names are written out, never built by
 *  string concatenation — Tailwind scans source text and a composed class name
 *  is a class that does not exist in the stylesheet. */
export interface ChartSeries {
  key: SeriesKey
  labelKey: 'activity.colIn' | 'activity.colOut' | 'activity.colMissed' | 'activity.colOutNoAnswer'
  /** The line, as a Tailwind stroke class. Follows the theme. */
  stroke: string
  /** The legend swatch. */
  swatch: string
  /** The area fill under a volume line. Empty for a problem line. */
  fill: string
  /** The same colour as a literal, for the canvas that goes into the file. */
  hex: string
  /** Drawn as a filled area (volume) or as a bare line (a problem). */
  area: boolean
  /** Visible by default. */
  on: boolean
}

/**
 * Order and default visibility.
 *
 * Volume series (incoming / outgoing) are areas and are on. Problem series are
 * lines and are OFF by default: they are an order of magnitude smaller than the
 * volume (measured ~500 against ~140) and drawing all four at once makes none
 * of them readable. "Missed" is left ON because it is the subject of the
 * report.
 */
export const SERIES: readonly ChartSeries[] = [
  {
    key: 'inbound',
    labelKey: 'activity.colIn',
    stroke: 'stroke-accent',
    swatch: 'bg-accent',
    fill: 'fill-accent/10',
    hex: '#215A8C',
    area: true,
    on: true,
  },
  {
    key: 'outbound',
    labelKey: 'activity.colOut',
    stroke: 'stroke-good',
    swatch: 'bg-good',
    fill: 'fill-good/10',
    hex: '#1E8052',
    area: true,
    on: true,
  },
  {
    key: 'missed',
    labelKey: 'activity.colMissed',
    stroke: 'stroke-bad',
    swatch: 'bg-bad',
    fill: '',
    hex: '#CC1E36',
    area: false,
    on: true,
  },
  {
    key: 'outbound_no_answer',
    labelKey: 'activity.colOutNoAnswer',
    stroke: 'stroke-warn',
    swatch: 'bg-warn',
    fill: '',
    hex: '#B35C05',
    area: false,
    on: false,
  },
]

/** The series hidden when the page first renders. */
export function defaultHidden(): Set<SeriesKey> {
  return new Set(SERIES.filter((series) => !series.on).map((series) => series.key))
}

/**
 * Where "good" stops and "needs attention" starts, for the callback RATE.
 *
 * Measured, not invented: the company average was ~75 %, the best employees
 * 90 %+, the worst 43 %. So 90 and 60 are the real edges of the real spread.
 */
export const RATE_GOOD = 90
export const RATE_WARN = 60

/**
 * The same for the callback TIME, in minutes.
 *
 * Also measured: the fastest teams 2-3 minutes, the slowest 43, company median
 * 6. ⚠️ Independent of the rate on purpose — a high rate does not excuse being
 * slow. One team returned 89 % of calls with a 43-minute median, and the rate
 * alone said they were doing well.
 */
export const MEDIAN_GOOD = 10
export const MEDIAN_WARN = 30

export type Tone = 'good' | 'warn' | 'bad' | 'none'

/** No value, no tone: an employee with no missed calls is neither green nor red. */
export function rateTone(rate: number | null): Tone {
  if (rate === null) return 'none'
  if (rate >= RATE_GOOD) return 'good'
  if (rate >= RATE_WARN) return 'warn'
  return 'bad'
}

export function medianTone(minutes: number | null): Tone {
  if (minutes === null) return 'none'
  if (minutes <= MEDIAN_GOOD) return 'good'
  if (minutes <= MEDIAN_WARN) return 'warn'
  return 'bad'
}

/** Screen rendering of a tone. Written out, never composed. */
export const TONE_CLASS: Record<Tone, string> = {
  good: 'text-good',
  warn: 'text-warn',
  bad: 'text-bad',
  none: 'text-muted',
}

/** File rendering of the same tone. `undefined` leaves the cell's own colour. */
export const TONE_HEX: Record<Tone, string | undefined> = {
  good: '#1E8052',
  warn: '#B35C05',
  bad: '#CC1E36',
  none: undefined,
}
