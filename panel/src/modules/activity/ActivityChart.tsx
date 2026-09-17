/**
 * Call volume over the window — ONE chart, TWO cuts.
 *
 * Ported from BonviZvonki `web/src/modules/activity/CallsChart.tsx`. The
 * behaviour is theirs; the drawing is not.
 *
 * THE CUT IS CHOSEN AUTOMATICALLY:
 *   · window longer than a day → by DAY;
 *   · window exactly one day   → by HOUR.
 *
 * Why automatic. There used to be two charts. With a one-day window the daily
 * one collapsed to a single point and was useless, and the hourly one summed
 * hours across a whole month whenever the window was long. In every case one of
 * the two was noise. Now the cut follows the window and only the meaningful
 * view is on screen.
 *
 * TOGGLING LINES. Four series at once cannot be read: incoming runs around 500
 * and missed around 140, so the small one is a flat line along the axis. Volume
 * series are on by default, problem series are chosen — except "missed", which
 * stays on because it is the subject of the report.
 *
 * ⚠️ There is no SCORE and no ranking here, and there will not be: this section
 * is about call statistics. Counts and points on one axis would rob both of
 * their meaning.
 *
 * ── HOW IT IS DRAWN ───────────────────────────────────────────
 * By hand, in SVG, with the same geometry the dashboard's call-flow chart uses
 * (`@/modules/dashboard/chart`) — one set of axis arithmetic in this product,
 * not two. BonviZvonki uses Recharts; that cannot come across, for the reasons
 * CONVENTIONS-CLIENT.md §3 and §11 give: colour here is a CSS custom property
 * that changes with the theme and a library taking hex strings cannot follow
 * it, and every such library writes `style={{...}}`, which is forbidden.
 *
 * Which series are hidden is the PAGE's state, not this component's: the
 * picture that goes into the Excel file has to show the same lines as the
 * screen, or the reader sees a line they switched off reappear in the file.
 */
import { useCallback, useLayoutEffect, useRef, useState } from 'react'

import {
  CHART,
  labelStride,
  linePath,
  nearestIndex,
  niceMax,
  plotWidth,
  xAt,
  yAt,
  yTicks,
} from '@/modules/dashboard/chart'
import { cn } from '@/shared/lib/cn'
import { formatCount } from '@/shared/lib/format'
import { EmptyState } from '@/shared/ui/QueryBoundary'

import type { ActivityDay, ActivityHour } from './api'
import { t } from '@/shared/i18n'
import { SERIES, type SeriesKey } from './series'

/** One x position: its label and the four values behind it. */
interface Point {
  label: string
  /** The full label, for the readout above the plot. */
  title: string
  values: Record<SeriesKey, number>
}

function dayPoint(row: ActivityDay): Point {
  // `dd.MM` — fits even at 30 points. Sliced off the ISO string rather than
  // parsed: these are Asia/Tashkent calendar dates and `new Date('2026-09-15')`
  // is midnight UTC, which renders as the 14th west of Tashkent.
  const label = `${row.day.slice(8, 10)}.${row.day.slice(5, 7)}`
  return {
    label,
    title: `${row.day.slice(8, 10)}.${row.day.slice(5, 7)}.${row.day.slice(0, 4)}`,
    values: {
      inbound: row.inbound,
      outbound: row.outbound,
      missed: row.missed,
      outbound_no_answer: row.outbound_no_answer,
    },
  }
}

function hourPoint(row: ActivityHour): Point {
  const label = String(row.hour).padStart(2, '0')
  return {
    label,
    title: t('activity.hourLabel', { hour: label }),
    values: {
      inbound: row.inbound,
      outbound: row.outbound,
      missed: row.missed,
      outbound_no_answer: row.outbound_no_answer,
    },
  }
}

/**
 * The card's own width, measured.
 *
 * A chart cannot be laid out in CSS alone: the x of every point is a number and
 * that number depends on how wide the card turned out. `ResizeObserver` is
 * guarded because jsdom has none — a test must render the chart, not crash on
 * it.
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

/** A volume series as a closed shape: the line, then down to the baseline. */
function areaPath(values: readonly number[], max: number, width: number): string {
  const line = linePath(values, max, width)
  if (!line) return ''
  const baseline = CHART.height - CHART.padBottom
  const last = xAt(values.length - 1, values.length, width)
  const first = xAt(0, values.length, width)
  return `${line} L ${last} ${baseline} L ${first} ${baseline} Z`
}

export function ActivityChart({
  days,
  hours,
  byHour,
  hidden,
  onToggle,
}: {
  days: readonly ActivityDay[]
  hours: readonly ActivityHour[]
  /** `true` — the hourly cut, i.e. the window is exactly one day. */
  byHour: boolean
  hidden: ReadonlySet<SeriesKey>
  onToggle: (key: SeriesKey) => void
}) {
  const [ref, width] = useMeasuredWidth()
  const [hovered, setHovered] = useState<number | null>(null)

  const points: Point[] = byHour ? hours.map(hourPoint) : days.map(dayPoint)
  const visible = SERIES.filter((series) => !hidden.has(series.key))

  const max = niceMax(
    Math.max(0, ...points.flatMap((point) => visible.map((s) => point.values[s.key]))),
  )
  const ticks = yTicks(max)
  const stride = labelStride(points.length, width)
  const right = CHART.padLeft + plotWidth(width)
  const current = hovered === null ? null : (points[hovered] ?? null)

  const move = useCallback(
    (step: number) => {
      const next = hovered === null ? points.length - 1 : hovered + step
      setHovered(Math.max(0, Math.min(points.length - 1, next)))
    },
    [hovered, points.length],
  )

  return (
    <div>
      {/* Our own legend rather than a library's: it has to be pressable and the
          off state has to be obvious. A standard legend marks it with opacity
          alone and nobody notices. */}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        {SERIES.map((series) => {
          const off = hidden.has(series.key)
          const value =
            current !== null
              ? current.values[series.key]
              : points.reduce((sum, point) => sum + point.values[series.key], 0)
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
              <span className={cn('text-muted', off && 'line-through')}>
                {t(series.labelKey)}
              </span>
              <span className="font-medium tabular-nums text-text">{formatCount(value)}</span>
            </button>
          )
        })}
      </div>

      {points.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">{t('common.empty')}</p>
      ) : visible.length === 0 ? (
        /* Every line switched off leaves an empty box, and an empty box is
           indistinguishable from "no data" — the reader may well have
           forgotten they did it. */
        <EmptyState title={t('activity.allHidden')} />
      ) : (
        <div ref={ref} className="w-full">
          {/* The readout replaces a floating tooltip, which would need
              `style={{ left }}` — forbidden (§11) — and which covers the line
              it describes and vanishes when a finger lifts. */}
          <p className="text-xs text-muted">{current?.title ?? ' '}</p>
          <svg
            width={Math.max(width, CHART.minWidth)}
            height={CHART.height}
            role="img"
            tabIndex={0}
            aria-label={t('activity.chartAria', { n: points.length })}
            className="max-w-full touch-none focus-visible:rounded-md"
            onMouseMove={(event) => {
              const box = event.currentTarget.getBoundingClientRect()
              setHovered(nearestIndex(event.clientX - box.left, points.length, width))
            }}
            onMouseLeave={() => setHovered(null)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight') move(1)
              else if (event.key === 'ArrowLeft') move(-1)
              else return
              event.preventDefault()
            }}
          >
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

            {points.map((point, index) =>
              index % stride === 0 || index === points.length - 1 ? (
                <text
                  key={point.label}
                  x={xAt(index, points.length, width)}
                  y={CHART.height - 6}
                  textAnchor="middle"
                  className="fill-muted text-[10px] tabular-nums"
                >
                  {point.label}
                </text>
              ) : null,
            )}

            {hovered !== null ? (
              <line
                x1={xAt(hovered, points.length, width)}
                x2={xAt(hovered, points.length, width)}
                y1={CHART.padTop}
                y2={CHART.height - CHART.padBottom}
                className="stroke-muted/50"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
            ) : null}

            {/* Areas first, lines after: a problem line must never end up
                behind a volume area. */}
            {visible
              .filter((series) => series.area)
              .map((series) => (
                <path
                  key={`area-${series.key}`}
                  d={areaPath(
                    points.map((point) => point.values[series.key]),
                    max,
                    width,
                  )}
                  className={cn('stroke-none', series.fill)}
                />
              ))}

            {visible.map((series) => (
              <path
                key={series.key}
                d={linePath(
                  points.map((point) => point.values[series.key]),
                  max,
                  width,
                )}
                className={cn('fill-none', series.stroke)}
                strokeWidth={series.area ? 2 : 2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}
          </svg>
        </div>
      )}
    </div>
  )
}
