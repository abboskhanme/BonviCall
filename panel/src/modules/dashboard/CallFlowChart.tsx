/**
 * The dashboard's call flow: UC-11's five classes over a week, a month or a
 * year, as five lines.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * It obeys the same rule as the tiles beside it — a number with no route is
 * trivia. Every point links through to `/calls` filtered to exactly the calls
 * it was drawn from, and the figures reconcile because the server aggregates
 * the same filtered query the list pages (`CallService.stats`).
 *
 * Drawn by hand in SVG rather than with a charting library. Three reasons, in
 * order: the colour tokens are CSS custom properties that change with the
 * theme and with `data-theme`, and a library that takes hex strings cannot
 * follow them (CONVENTIONS-CLIENT.md §3); `style={{...}}` is forbidden (§11)
 * and every such library writes inline styles; and the whole shape is five
 * polylines, which is less code than the adapter would be.
 *
 * The period lives in the URL (`?period=month`), because screen state does
 * (§2) — a chart somebody wants to show a colleague has to be linkable.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LineChart } from 'lucide-react'

import { useCallStats, type CallStats, type CallStatsBucket } from '@/modules/calls/api'
import { CALL_CLASS_FILTER, CALL_CLASS_LABEL, type CallClass } from '@/modules/calls/labels'
import { isComplete, type PeriodSelection } from './period'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { formatCount } from '@/shared/lib/format'
import { Card } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  CHART,
  bucketLabel,
  bucketTitle,
  labelStride,
  linePath,
  nearestIndex,
  niceMax,
  plotWidth,
  xAt,
  yAt,
  yTicks,
} from './chart'

/**
 * The five lines, in the order a reader looks for them: what worked first,
 * what did not after it.
 *
 * The classes borrow the semantic tokens rather than inventing a palette —
 * answered is `good`, missed is `bad`, rejected is `warn` — so the colours
 * mean here what they mean everywhere else in the panel, and all five follow
 * the theme. `text-*` doubles as the legend swatch through `fill-current`.
 */
const SERIES: ReadonlyArray<{ key: CallClass; line: string; dot: string; swatch: string }> = [
  { key: 'incoming_answered', line: 'stroke-good', dot: 'fill-good', swatch: 'bg-good' },
  { key: 'outgoing_answered', line: 'stroke-accent', dot: 'fill-accent', swatch: 'bg-accent' },
  { key: 'missed', line: 'stroke-bad', dot: 'fill-bad', swatch: 'bg-bad' },
  { key: 'rejected', line: 'stroke-warn', dot: 'fill-warn', swatch: 'bg-warn' },
  { key: 'no_answer', line: 'stroke-muted', dot: 'fill-muted', swatch: 'bg-muted' },
]

/**
 * The card's own width, measured.
 *
 * A chart cannot be laid out in CSS alone: the x of every point is a number,
 * and the number depends on how wide the card turned out to be. `ResizeObserver`
 * is guarded because jsdom has none — a test must render the chart, not crash
 * on it — and the fallback width is the one the layout gives on a laptop.
 */
function useMeasuredWidth(): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(CHART.minWidth * 2)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => setWidth(element.clientWidth || CHART.minWidth * 2)
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, width]
}

/** `/calls` for one bucket, optionally narrowed to one of the five classes. */
function callsLink(bucket: CallStatsBucket, series?: CallClass): string {
  const search = new URLSearchParams({ date_from: bucket.date_from, date_to: bucket.date_to })
  if (series) {
    const filter = CALL_CLASS_FILTER[series]
    search.set('direction', filter.direction)
    search.set('disposition', filter.disposition)
  }
  return `/calls?${search.toString()}`
}

function Plot({
  stats,
  hidden,
  hovered,
  onHover,
}: {
  stats: CallStats
  hidden: ReadonlySet<CallClass>
  hovered: number | null
  onHover: (index: number | null) => void
}) {
  const navigate = useNavigate()
  const [ref, width] = useMeasuredWidth()
  const buckets = stats.buckets
  const visible = SERIES.filter((series) => !hidden.has(series.key))

  const max = niceMax(
    Math.max(0, ...buckets.flatMap((bucket) => visible.map((series) => bucket[series.key]))),
  )
  const ticks = yTicks(max)
  const stride = labelStride(buckets.length, width)
  const right = CHART.padLeft + plotWidth(width)

  const move = useCallback(
    (step: number) => {
      const next = hovered === null ? buckets.length - 1 : hovered + step
      onHover(Math.max(0, Math.min(buckets.length - 1, next)))
    },
    [buckets.length, hovered, onHover],
  )

  /** The hovered bucket, or null. `noUncheckedIndexedAccess` is on, and the
   *  index outliving its period is exactly the bug it exists to catch. */
  const current = hovered === null ? null : (buckets[hovered] ?? null)

  /** Open the calls behind a bucket. The index comes from the event where
   *  there is one: a click must open what was clicked, not what the last
   *  `mousemove` happened to leave behind — on a touchscreen there is no
   *  `mousemove` at all. */
  const open = (index: number | null) => {
    const bucket = index === null ? null : (buckets[index] ?? null)
    if (bucket) navigate(callsLink(bucket))
  }

  return (
    <div ref={ref} className="w-full">
      <svg
        width={Math.max(width, CHART.minWidth)}
        height={CHART.height}
        role="img"
        tabIndex={0}
        aria-label={t('dashboard.chart.aria', {
          from: stats.date_from,
          to: stats.date_to,
          n: formatCount(buckets.reduce((sum, bucket) => sum + bucket.total, 0)),
        })}
        className="max-w-full touch-none focus-visible:rounded-md"
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect()
          onHover(nearestIndex(event.clientX - box.left, buckets.length, width))
        }}
        onMouseLeave={() => onHover(null)}
        onClick={(event) => {
          const box = event.currentTarget.getBoundingClientRect()
          const index = nearestIndex(event.clientX - box.left, buckets.length, width)
          onHover(index)
          open(index)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight') move(1)
          else if (event.key === 'ArrowLeft') move(-1)
          else if (event.key === 'Enter') open(hovered)
          else return
          event.preventDefault()
        }}
      >
        {/* Gridlines and the y scale. Drawn first so every line sits on top. */}
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={CHART.padLeft}
              x2={right}
              y1={yAt(tick, max)}
              y2={yAt(tick, max)}
              className="stroke-border"
              strokeWidth={1}
            />
            <text
              x={CHART.padLeft - 8}
              y={yAt(tick, max) + 3}
              textAnchor="end"
              className="fill-muted text-[10px] tabular-nums"
            >
              {tick}
            </text>
          </g>
        ))}

        {buckets.map((bucket, index) =>
          index % stride === 0 || index === buckets.length - 1 ? (
            <text
              key={bucket.date_from}
              x={xAt(index, buckets.length, width)}
              y={CHART.height - 6}
              textAnchor="middle"
              className="fill-muted text-[10px] tabular-nums"
            >
              {bucketLabel(bucket, stats.granularity)}
            </text>
          ) : null,
        )}

        {hovered !== null ? (
          <line
            x1={xAt(hovered, buckets.length, width)}
            x2={xAt(hovered, buckets.length, width)}
            y1={CHART.padTop}
            y2={CHART.height - CHART.padBottom}
            className="stroke-muted/50"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        ) : null}

        {visible.map((series) => (
          <path
            key={series.key}
            d={linePath(
              buckets.map((bucket) => bucket[series.key]),
              max,
              width,
            )}
            className={cn('fill-none', series.line)}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}

        {current !== null && hovered !== null
          ? visible.map((series) => (
              <circle
                key={series.key}
                cx={xAt(hovered, buckets.length, width)}
                cy={yAt(current[series.key], max)}
                r={3}
                className={series.dot}
              />
            ))
          : null}
      </svg>
    </div>
  )
}

/** The legend, which is also the readout: hovering a bucket puts ITS numbers here. */
function Legend({
  stats,
  hidden,
  hovered,
  onToggle,
}: {
  stats: CallStats
  hidden: ReadonlySet<CallClass>
  hovered: number | null
  onToggle: (series: CallClass) => void
}) {
  const bucket = hovered === null ? null : (stats.buckets[hovered] ?? null)
  return (
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
      {SERIES.map((series) => {
        const value =
          bucket !== null
            ? bucket[series.key]
            : stats.buckets.reduce((sum, point) => sum + point[series.key], 0)
        const off = hidden.has(series.key)
        return (
          <button
            key={series.key}
            type="button"
            onClick={() => onToggle(series.key)}
            aria-pressed={!off}
            className={cn(
              'flex items-center gap-2 text-xs transition-opacity',
              off ? 'opacity-40' : 'opacity-100',
            )}
          >
            <span className={cn('size-2 rounded-sm', series.swatch)} aria-hidden />
            <span className="text-muted">{t(CALL_CLASS_LABEL[series.key])}</span>
            <span className="font-medium tabular-nums text-text">{formatCount(value)}</span>
          </button>
        )
      })}
    </div>
  )
}

/**
 * The line above the plot: the window while nothing is hovered, and the
 * hovered bucket's own date and total while one is.
 *
 * It replaces a floating tooltip, which would need `style={{ left }}` — and
 * inline styles are forbidden (CONVENTIONS-CLIENT.md §11). A fixed readout is
 * better anyway: it never covers the line it describes, and it does not
 * disappear on a touchscreen the moment a finger lifts.
 */
function readout(stats: CallStats, hovered: number | null): string {
  const bucket = hovered === null ? undefined : stats.buckets[hovered]
  if (bucket) {
    return t('dashboard.chart.bucket', {
      when: bucketTitle(bucket, stats.granularity),
      n: formatCount(bucket.total),
    })
  }
  const first = stats.buckets[0]
  const last = stats.buckets[stats.buckets.length - 1]
  if (!first || !last) return t('dashboard.chart.silent')
  return t('dashboard.chart.range', {
    from: bucketTitle(first, stats.granularity),
    to: bucketTitle(last, stats.granularity),
  })
}

export function CallFlowChart({ selection }: { selection: PeriodSelection }) {
  const query = useCallStats(selection)
  const [hidden, setHidden] = useState<ReadonlySet<CallClass>>(new Set())
  const [hovered, setHovered] = useState<number | null>(null)

  // A bucket index means nothing once the window changes underneath it: the
  // seventh point of a week is not the seventh point of a year.
  useEffect(
    () => setHovered(null),
    [selection.period, selection.date_from, selection.date_to],
  )

  const toggle = (series: CallClass) => {
    setHidden((current) => {
      const next = new Set(current)
      // The last visible line may not be hidden: an empty plot area is
      // indistinguishable from a broken one.
      if (next.has(series)) next.delete(series)
      else if (next.size < SERIES.length - 1) next.add(series)
      return next
    })
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wide text-muted">
            <LineChart className="size-4" aria-hidden />
            {t('dashboard.chart.title')}
          </p>
          <p className="mt-1 text-xs text-muted">{t('dashboard.chart.hint')}</p>
        </div>
      </div>

      {!isComplete(selection) ? (
        // A half-chosen range is not a loading state: the request is not in
        // flight, it is waiting for the second date. A skeleton here would
        // spin forever and read as a broken page.
        <p className="mt-6 text-sm text-muted">{t('dashboard.chart.pickBothDates')}</p>
      ) : (
      <QueryBoundary query={query} skeletonRows={4}>
        {(stats) => (
          <div className="mt-3">
            <p className="text-xs text-muted">{readout(stats, hovered)}</p>
            <Plot stats={stats} hidden={hidden} hovered={hovered} onHover={setHovered} />
            <Legend stats={stats} hidden={hidden} hovered={hovered} onToggle={toggle} />
            {stats.buckets.every((bucket) => bucket.total === 0) ? (
              // Deliberately a line under a drawn chart rather than an empty
              // card: "no calls this week" is itself the answer, and an empty
              // state would hide the axis that says which week.
              <p className="mt-2 text-xs text-muted">{t('dashboard.chart.silent')}</p>
            ) : null}
          </div>
        )}
      </QueryBoundary>
      )}
    </Card>
  )
}
