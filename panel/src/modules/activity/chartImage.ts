/**
 * Draws the trend chart as a PNG, for the Excel file.
 *
 * Ported from BonviZvonki `web/src/modules/activity/chartImage.ts`. Comments
 * translated (CONVENTIONS.md §14); the geometry, the monotone interpolation and
 * the label thinning are theirs, line for line.
 *
 * WHY A PICTURE AT ALL. Whoever opens the spreadsheet looks at the chart first:
 * thirty rows of numbers do not answer "what happened that day" and a line
 * does, at a glance. Without it the file is an incomplete copy of the screen
 * and the reader opens the browser anyway to compare.
 *
 * WHY NOT LIFT THE SVG OFF THE PAGE. The chart on screen takes its colours from
 * CSS custom properties (`stroke-accent` → `hsl(var(--accent))`). Detached from
 * the document those variables are GONE and the image comes out black or
 * transparent. The on-screen size is the browser window's, too — 900px for one
 * reader and 1400px for another — so the file would differ per person. This
 * redraws from the NUMBERS at a fixed size instead.
 *
 * ⚠️ THE FILE MUST STILL BE PRODUCED WITHOUT IT. If drawing fails — canvas
 * disabled, no memory, a test environment with no 2D context — this returns
 * `null` and the export carries on. The numbers matter more than the picture,
 * and every one of them is on sheet 3 anyway.
 */
import type { SeriesKey } from './series'

/* ── Size ─────────────────────────────────────────────────────
   The logical size is the on-screen chart's proportion. `SCALE` is pixel
   density: the image is placed in Excel at half its pixel size (through
   `dpi`), so lines stay smooth on a retina screen and in print. */
const WIDTH = 820
const HEIGHT = 320
const SCALE = 2

const PAD = { top: 58, right: 16, bottom: 26, left: 46 }

/** `--text`, `--muted` and `--border` of the LIGHT theme (src/index.css).
 *  The image is always drawn on white; it has no theme to follow. */
const INK = '#151D28'
const MUTED = '#677383'
const GRID = '#E3E7ED'

const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif'

export interface ChartImage {
  blob: Blob
  /** Pixels. Excel turns these plus `dpi` into a size on the sheet. */
  width: number
  height: number
  /** `96 * SCALE`, so the image appears at its logical size. */
  dpi: number
}

export interface ChartInput {
  /** The x label (`30.08` or `08:00`) and the row's values. */
  points: { label: string; values: Record<SeriesKey, number> }[]
  /** The series to draw — the ones VISIBLE on screen. */
  series: { key: SeriesKey; label: string; hex: string; area: boolean }[]
  title: string
}

/** `#215A8C` → `rgba(33, 90, 140, 0.2)`. */
function alpha(hex: string, value: number): string {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${value})`
}

/**
 * The axis top and its step, in round numbers.
 *
 * 587 gives 600/150; 1234 gives 1500/500. The raw maximum cannot be used: the
 * axis would read 587, 440, 293 and nobody can take a value off that.
 */
export function niceScale(max: number): { top: number; step: number } {
  if (!(max > 0)) return { top: 1, step: 1 }
  const rough = max / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const norm = rough / magnitude
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * magnitude
  return { top: Math.ceil(max / step) * step, step }
}

/**
 * Monotone cubic tangents (Fritsch-Carlson).
 *
 * The on-screen chart is drawn with straight segments, but a smoothed curve
 * reads better at this size — and plain smoothing (Catmull-Rom) INVENTS peaks
 * the data does not have: around one tall day between two low ones the curve
 * dips BELOW ZERO, which in a report reads as a negative number of calls.
 */
export function tangents(ys: number[], dx: number): number[] {
  const n = ys.length
  const secants = Array.from({ length: n - 1 }, (_, i) => ((ys[i + 1] ?? 0) - (ys[i] ?? 0)) / dx)
  const m = new Array<number>(n)

  m[0] = secants[0] ?? 0
  m[n - 1] = secants[n - 2] ?? 0
  for (let i = 1; i < n - 1; i++) {
    const before = secants[i - 1] ?? 0
    const after = secants[i] ?? 0
    m[i] = before * after <= 0 ? 0 : (before + after) / 2
  }

  for (let i = 0; i < n - 1; i++) {
    const secant = secants[i] ?? 0
    if (secant === 0) {
      m[i] = 0
      m[i + 1] = 0
      continue
    }
    const a = (m[i] ?? 0) / secant
    const b = (m[i + 1] ?? 0) / secant
    const s = a * a + b * b
    if (s > 9) {
      const tau = 3 / Math.sqrt(s)
      m[i] = tau * a * secant
      m[i + 1] = tau * b * secant
    }
  }
  return m
}

/** A monotone curve through the points; leaves an open path on `ctx`. */
function curve(ctx: CanvasRenderingContext2D, xs: number[], ys: number[]): void {
  const dx = xs.length > 1 ? (xs[1] ?? 0) - (xs[0] ?? 0) : 0
  const m = tangents(ys, dx)

  ctx.moveTo(xs[0] ?? 0, ys[0] ?? 0)
  for (let i = 0; i < xs.length - 1; i++) {
    ctx.bezierCurveTo(
      (xs[i] ?? 0) + dx / 3,
      (ys[i] ?? 0) + ((m[i] ?? 0) * dx) / 3,
      (xs[i + 1] ?? 0) - dx / 3,
      (ys[i + 1] ?? 0) - ((m[i + 1] ?? 0) * dx) / 3,
      xs[i + 1] ?? 0,
      ys[i + 1] ?? 0,
    )
  }
}

export async function renderChartImage({
  points,
  series,
  title,
}: ChartInput): Promise<ChartImage | null> {
  /* One point is not a line, and no series is nothing to draw. An empty frame
     in the file would read as "there is no data", which is a different and
     false statement. */
  if (points.length < 2 || !series.length) return null

  const canvas = document.createElement('canvas')
  canvas.width = WIDTH * SCALE
  canvas.height = HEIGHT * SCALE
  const ctx = canvas.getContext('2d')
  if (!ctx) return null

  ctx.scale(SCALE, SCALE)
  ctx.fillStyle = '#FFFFFF'
  ctx.fillRect(0, 0, WIDTH, HEIGHT)
  ctx.textBaseline = 'middle'

  const plot = {
    left: PAD.left,
    right: WIDTH - PAD.right,
    top: PAD.top,
    bottom: HEIGHT - PAD.bottom,
  }
  const plotWidth = plot.right - plot.left
  const plotHeight = plot.bottom - plot.top

  /* ── Title and legend ─────────────────────────────────────
     The image may be copied out of the spreadsheet into another document, so
     it has to stand on its own: coloured lines with no title say nothing. */
  ctx.fillStyle = INK
  ctx.font = `600 14px ${FONT}`
  ctx.textAlign = 'left'
  ctx.fillText(title, plot.left - PAD.left + 2, 18)

  let legendX = plot.left - PAD.left + 2
  ctx.font = `11px ${FONT}`
  for (const item of series) {
    ctx.fillStyle = item.hex
    /* `roundRect` is missing in older browsers. The rounding is decoration and
       its absence must not take the whole image down. */
    if (typeof ctx.roundRect === 'function') {
      ctx.beginPath()
      ctx.roundRect(legendX, 39, 16, 2.5, 1.25)
      ctx.fill()
    } else {
      ctx.fillRect(legendX, 39, 16, 2.5)
    }
    ctx.fillStyle = MUTED
    ctx.fillText(item.label, legendX + 22, 40)
    legendX += 22 + ctx.measureText(item.label).width + 18
  }

  /* ── Axes ─────────────────────────────────────────────── */
  const max = Math.max(
    ...points.flatMap((point) => series.map((item) => point.values[item.key] ?? 0)),
  )
  const scale = niceScale(max)
  const y = (value: number) => plot.bottom - (value / scale.top) * plotHeight
  const xs = points.map(
    (_, index) => plot.left + (index * plotWidth) / (points.length - 1),
  )

  ctx.font = `11px ${FONT}`
  for (let value = 0; value <= scale.top + 0.5; value += scale.step) {
    const line = Math.round(y(value)) + 0.5
    ctx.strokeStyle = GRID
    ctx.lineWidth = 1
    ctx.setLineDash(value === 0 ? [] : [3, 3])
    ctx.beginPath()
    ctx.moveTo(plot.left, line)
    ctx.lineTo(plot.right, line)
    ctx.stroke()

    ctx.setLineDash([])
    ctx.fillStyle = MUTED
    ctx.textAlign = 'right'
    ctx.fillText(String(value), plot.left - 8, y(value))
  }

  /* x labels — as many as fit. Written close together they overlap and the
     dates become a black smear. */
  const widest = Math.max(...points.map((point) => ctx.measureText(point.label).width))
  const gap = points.length > 1 ? plotWidth / (points.length - 1) : plotWidth
  const every = Math.max(1, Math.ceil((widest + 14) / gap))
  const last = points.length - 1
  const ticks = points.map((_, index) => index).filter((index) => index % every === 0)
  /* The final day is the edge of the report and has to be visible. The stride
     may not land on it (counting 30 days by twos stops at 29), so it is added
     — but only if there is room, or the last two dates collide. */
  const lastTick = ticks[ticks.length - 1] ?? 0
  if (!ticks.includes(last) && (last - lastTick) * gap >= widest + 10) {
    ticks.push(last)
  }
  ctx.fillStyle = MUTED
  for (const index of ticks) {
    /* Edge labels must not run off the image: the first is left-aligned, the
       last right-aligned. */
    ctx.textAlign = index === 0 ? 'left' : index === last ? 'right' : 'center'
    ctx.fillText(points[index]?.label ?? '', xs[index] ?? 0, plot.bottom + 13)
  }

  /* ── The series ───────────────────────────────────────────
     Areas first, lines after: a problem line (missed) must not end up behind
     a volume area. */
  const draw = (item: (typeof series)[number]) => {
    const ys = points.map((point) => y(point.values[item.key] ?? 0))

    if (item.area) {
      const fill = ctx.createLinearGradient(0, plot.top, 0, plot.bottom)
      fill.addColorStop(0, alpha(item.hex, 0.2))
      fill.addColorStop(1, alpha(item.hex, 0))
      ctx.beginPath()
      curve(ctx, xs, ys)
      ctx.lineTo(xs[xs.length - 1] ?? 0, plot.bottom)
      ctx.lineTo(xs[0] ?? 0, plot.bottom)
      ctx.closePath()
      ctx.fillStyle = fill
      ctx.fill()
    }

    ctx.beginPath()
    curve(ctx, xs, ys)
    ctx.strokeStyle = item.hex
    ctx.lineWidth = item.area ? 2 : 2.5
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.stroke()

    /* Dots only on a sparse chart. Past ~30 points they thicken the line and
       stop being visible as dots. */
    if (!item.area && points.length <= 31) {
      ctx.fillStyle = item.hex
      xs.forEach((x, index) => {
        ctx.beginPath()
        ctx.arc(x, ys[index] ?? 0, 2, 0, Math.PI * 2)
        ctx.fill()
      })
    }
  }

  series.filter((item) => item.area).forEach(draw)
  series.filter((item) => !item.area).forEach(draw)

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/png'),
  )
  if (!blob) return null

  return { blob, width: canvas.width, height: canvas.height, dpi: 96 * SCALE }
}
