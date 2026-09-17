/**
 * The four analytics charts — Recharts, ported from
 * `../BonviZvonki/services/web/src/modules/dashboard/components/charts.tsx`.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Why a charting library here, when `modules/dashboard/CallFlowChart.tsx`
 * draws its own SVG.** That file gives three reasons and two of them still
 * hold; what changed is the third. Its shape is five polylines, which is less
 * code than an adapter — this page's is a stacked area with two axes, a radar,
 * a vertical bar chart with per-bar colours and a horizontal one, and
 * hand-rolling four of those is several hundred lines of geometry with no test
 * that could tell a wrong arc from a right one.
 *
 * The two reasons that do hold are obeyed rather than traded away:
 *
 *   · **colour is a CSS token**, never a hex literal — Recharts takes colour as
 *     a prop, so the prop carries the token expression itself and the chart
 *     follows light, dark and system themes (`chart.ts::CHART_COLOR`);
 *   · **no inline `style` in this file.** The custom tooltip is built from the
 *     same `Card`-shaped classes as the rest of the panel, and its series dot
 *     is a Tailwind token class looked up from the series colour rather than a
 *     `style={{ background }}` — which is the one line of their tooltip that
 *     could not come across.
 *
 * Every empty state is the caller's: these components are handed data by a
 * `QueryBoundary` branch and render what they are given.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'

import type { BlockRow, TrendRow } from './chart'
import { CHART_COLOR, bucketColor, bucketLabel } from './chart'
import type { RedFlagCount, ScoreBucket } from './api'

/** Axis furniture, written once: eleven-point muted labels and no rules. */
const AXIS = {
  stroke: CHART_COLOR.muted,
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const

/** A tick label, as a plain object because Recharts styles ticks by prop. */
const TICK = { fill: CHART_COLOR.muted, fontSize: 11 } as const

/**
 * The series colour, back to a Tailwind token class.
 *
 * The tooltip needs a coloured dot and this panel does not write inline styles
 * (CONVENTIONS-CLIENT.md §11), so the colour a series was drawn with is mapped
 * to the class that paints the same token. Both sides come from `CHART_COLOR`,
 * so they cannot drift.
 */
const DOT_CLASS: Record<string, string> = {
  [CHART_COLOR.accent]: 'bg-accent',
  [CHART_COLOR.good]: 'bg-good',
  [CHART_COLOR.warn]: 'bg-warn',
  [CHART_COLOR.bad]: 'bg-bad',
  [CHART_COLOR.muted]: 'bg-muted',
}

/**
 * Recharts passes these through `content={<ChartTooltip />}`, so every field is
 * optional. Their file records why this is an interface and not `any`: with
 * `any` a mistyped `entry.color` was nobody's error.
 */
interface TooltipEntry {
  dataKey?: string | number
  name?: string | number
  value?: number | string | null
  color?: string
  fill?: string
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  label?: string | number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 shadow-pop">
      <p className="mb-1 text-2xs font-medium text-muted">{label}</p>
      {payload.map((entry) => (
        <p key={String(entry.dataKey)} className="flex items-center gap-2 text-xs">
          <span
            className={cn(
              'size-2 shrink-0 rounded-full',
              DOT_CLASS[entry.color ?? entry.fill ?? ''] ?? 'bg-muted',
            )}
            aria-hidden
          />
          <span className="text-muted">{entry.name}:</span>
          <span className="font-mono font-medium tabular-nums text-text">
            {entry.value ?? '—'}
          </span>
        </p>
      ))}
    </div>
  )
}

/* ── 1. The trend ─────────────────────────────────────────────────────────── */

/**
 * Average score over time, with the volume it was measured on.
 *
 * BonviZvonki drew the AI score against the customer's own CSAT rating on one
 * 0-100 axis. That second series is phase 3 here (no survey channel, §1.4), and
 * a single line would be a chart nobody can read a caveat from — so the volume
 * takes its place on a second axis. The pairing is the point: "78 on average"
 * means something different over 400 calls than over four.
 *
 * `connectNulls` is deliberately OFF for the score. A day nobody worked has no
 * average, and joining across it would draw a straight line through a gap as
 * though the score had held steady.
 */
export function TrendChart({ rows }: { rows: TrendRow[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      {/* `left: 0`, never negative. Theirs was -20, which pushed the plot over
          the y axis and cut its widest label: "100" rendered as "00". Space is
          won back with the axis's own `width`. */}
      <ComposedChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="analyticsScoreFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_COLOR.accent} stopOpacity={0.22} />
            <stop offset="100%" stopColor={CHART_COLOR.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={CHART_COLOR.border} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" {...AXIS} minTickGap={24} />
        {/* Three digits have to fit, or "100" loses its first character. */}
        <YAxis yAxisId="score" domain={[0, 100]} {...AXIS} width={34} />
        <YAxis
          yAxisId="calls"
          orientation="right"
          allowDecimals={false}
          {...AXIS}
          width={40}
        />
        <Tooltip content={<ChartTooltip />} />
        <Area
          yAxisId="score"
          type="monotone"
          dataKey="ai_score"
          name={t('analytics.seriesScore')}
          stroke={CHART_COLOR.accent}
          strokeWidth={2}
          fill="url(#analyticsScoreFill)"
        />
        <Line
          yAxisId="calls"
          type="monotone"
          dataKey="calls"
          name={t('analytics.seriesCalls')}
          stroke={CHART_COLOR.muted}
          strokeWidth={2}
          strokeDasharray="4 4"
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/* ── 2. The score histogram ───────────────────────────────────────────────── */

/**
 * Scored calls per ten-point band, each bar in the band's own colour.
 *
 * The server always sends ten bands, empty ones included, so the axis is the
 * whole 0-100 range whatever the data does — a histogram with holes in it reads
 * as a filter that ate rows.
 */
export function DistributionChart({ buckets }: { buckets: readonly ScoreBucket[] }) {
  const rows = buckets.map((bucket) => ({
    range: bucketLabel(bucket),
    floor: bucket.floor,
    calls: bucket.calls,
  }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={CHART_COLOR.border} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="range" {...AXIS} />
        {/* Four digits: a busy month passes a thousand calls in one band. */}
        <YAxis {...AXIS} width={40} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: CHART_COLOR.surface2 }} />
        <Bar dataKey="calls" name={t('analytics.seriesCalls')} radius={[4, 4, 0, 0]}>
          {rows.map((row) => (
            <Cell key={row.range} fill={bucketColor(row.floor)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ── 3. The rubric blocks ─────────────────────────────────────────────────── */

/**
 * The four rubric blocks as a radar, in percent of each block's own maximum.
 *
 * Percent and not points: the blocks carry different weights, so a radar of raw
 * points draws the rubric's weighting rather than the team's work. The axis is
 * fixed at 0-100 for the same reason their comment gives — the maxima once
 * came from a code constant that had drifted from the rubric, and the shape
 * left the chart at 106 %.
 */
export function BlocksChart({ rows }: { rows: BlockRow[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <RadarChart data={rows} outerRadius="72%">
        <PolarGrid stroke={CHART_COLOR.border} />
        <PolarAngleAxis dataKey="label" tick={TICK} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Tooltip content={<ChartTooltip />} />
        <Radar
          dataKey="percent"
          name={t('analytics.seriesBlockPercent')}
          stroke={CHART_COLOR.accent}
          fill={CHART_COLOR.accent}
          fillOpacity={0.2}
          strokeWidth={2}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

/* ── 4. The breaches ──────────────────────────────────────────────────────── */

/**
 * How often each kind of breach was found — horizontal, because the labels are
 * sentences and a vertical axis would stack them on their sides.
 *
 * The height grows with the number of kinds found, so two breaches do not leave
 * a card of white space and six do not squeeze into 140 pixels.
 */
export function RedFlagChart({ rows }: { rows: (RedFlagCount & { label: string })[] }) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(140, rows.length * 34)}>
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 0, right: 16, left: 0, bottom: 0 }}
      >
        <XAxis type="number" {...AXIS} hide allowDecimals={false} />
        <YAxis type="category" dataKey="label" {...AXIS} width={150} tick={TICK} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: CHART_COLOR.surface2 }} />
        <Bar
          dataKey="count"
          name={t('analytics.seriesFlags')}
          fill={CHART_COLOR.bad}
          radius={[0, 4, 4, 0]}
          barSize={16}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
