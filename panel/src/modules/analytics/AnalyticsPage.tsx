/**
 * `/analytics` — the analysis dashboard (SPEC-ANALYTICS phase 2).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Ported from `../BonviZvonki/services/web/src/modules/dashboard/DashboardPage.tsx`,
 * which is the page their whole `modules/analytics` backend exists to draw. Six
 * aggregates over one window: four KPI cards, the call-type strip that explains
 * them, the trend, three breakdown charts and the leaderboard.
 *
 * **It is a section of its own and touches nothing.** `DashboardPage.tsx`,
 * `CallsPage.tsx` and `CallDetailPage.tsx` keep working exactly as they do in
 * production (§7), so a mistake here cannot reach a screen the fleet already
 * depends on. The one link out goes to `/analysis`, which is where a reader
 * goes to see the conversations behind a number.
 *
 * Three rules this page follows and their reasons:
 *
 *   · **Every filter lives in the URL** (CONVENTIONS-CLIENT.md §2), so a
 *     manager can paste "last quarter, external only" to a colleague. Six
 *     queries share it, which is what stops a card and the chart under it
 *     describing different periods — the defect their own service comments
 *     record (4.18 in a card, 4.67 in the table beneath it).
 *   · **Loading, empty and error are `QueryBoundary`'s**, one per card: the
 *     leaderboard arriving late must not hold up the KPI row.
 *   · **The window shown is the SERVER's**, echoed back on every response.
 *     "Last 30 days" is resolved against Asia/Tashkent there, and a page that
 *     computed its own label from the browser's clock would caption the data
 *     with a period it was not measured over.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { Link, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  Clock,
  FilterX,
  ListChecks,
  Phone,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { blockLabel, redFlagLabel } from '@/modules/analysis/labels'
import { useAuth } from '@/modules/auth/store'
import { CALL_TYPE_LABEL } from '@/modules/calls/labels'
import { Perm } from '@/shared/auth/permissions'
import { t, type MessageKey } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount, formatDate, formatDuration } from '@/shared/lib/format'
import { Section } from '@/shared/ui/detail'
import { DateFilter, EnumFilter, FilterField, SELECT_CLASS } from '@/shared/ui/filters'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  useAgentRanking,
  useBlockBreakdown,
  useOverview,
  useRedFlagBreakdown,
  useScoreDistribution,
  useTimeseries,
  type AnalyticsOverview,
  type AnalyticsQuery,
  type Bucket,
} from './api'
import { AgentRankingTable } from './AgentRankingTable'
import { BlocksChart, DistributionChart, RedFlagChart, TrendChart } from './charts'
import { blockRows, deltaIsGood, toNumber, trendRows } from './chart'

/** The URL is the screen state; the names are the server's own query parameters. */
const PARAM_DAYS = 'days'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'
const PARAM_AGENT = 'agent_id'
const PARAM_CALL_TYPE = 'call_type'
const PARAM_BUCKET = 'bucket'

/** Every filter parameter, so "clear" cannot miss one — the bug where a reset
 *  button leaves a hidden filter in force. */
const FILTER_PARAMS = [
  PARAM_DAYS,
  PARAM_DATE_FROM,
  PARAM_DATE_TO,
  PARAM_AGENT,
  PARAM_CALL_TYPE,
] as const

/**
 * The presets, and the server's own default among them.
 *
 * Seven, thirty and ninety **calendar** days: the server resolves them in
 * Asia/Tashkent, whole days, because "the last 7 days" means seven calendar
 * days to a person and not 168 hours. BonviZvonki computed it both ways on two
 * neighbouring pages and reported 22,003 and 21,513 for one period.
 */
const PRESETS = [7, 30, 90] as const
const DEFAULT_DAYS = 30

const PRESET_LABEL: Record<number, MessageKey> = {
  7: 'analytics.period7',
  30: 'analytics.period30',
  90: 'analytics.period90',
}

const BUCKET_LABEL: Record<Bucket, MessageKey> = {
  day: 'analytics.bucketDay',
  week: 'analytics.bucketWeek',
  month: 'analytics.bucketMonth',
}

/** Pipeline order, not alphabetical: a reader moves along it. */
const BUCKETS: readonly Bucket[] = ['day', 'week', 'month']

/** The order the call types are read in: the ones that are analysed first,
 *  "not classified yet" last. Alphabetical would be meaningless. */
const CALL_TYPE_ORDER = ['external', 'internal', 'unknown'] as const

function parseDays(raw: string | null): number {
  const value = Number(raw)
  return PRESETS.includes(value as (typeof PRESETS)[number]) ? value : DEFAULT_DAYS
}

function parseEnum<T extends string>(raw: string | null, allowed: Record<T, unknown>) {
  // A pasted `?call_type=nearly` must not travel as a 422 somebody cannot act
  // on; an unknown value is simply no filter.
  return raw !== null && raw in allowed ? (raw as T) : undefined
}

/**
 * A row of mutually exclusive choices — the period presets and the trend's
 * bucket.
 *
 * **Not wrapped in `FilterField`**, which renders a `<label>`. A `<button>` is
 * a labelable element, so a label around three of them gives all three the
 * label's whole text as their accessible name ("Davr7 kun30 kun90 kun") and a
 * screen reader announces the same thing for each. The caption is a plain span,
 * and each button names itself.
 */
function SegmentedControl<T extends string | number>({
  label,
  options,
  value,
  labelOf,
  onSelect,
}: {
  label?: string
  options: readonly T[]
  value: T
  labelOf: (option: T) => string
  onSelect: (option: T) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      {label ? <span className="text-2xs font-medium text-muted">{label}</span> : null}
      <div
        className="flex rounded-md border border-border bg-surface p-0.5"
        role="group"
        aria-label={label}
      >
        {options.map((option) => (
          <button
            key={String(option)}
            type="button"
            onClick={() => onSelect(option)}
            aria-pressed={option === value}
            className={cn(
              'rounded-sm px-3 py-1 text-xs font-medium transition-colors',
              option === value ? 'bg-accent-soft text-accent' : 'text-muted hover:text-text',
            )}
          >
            {labelOf(option)}
          </button>
        ))}
      </div>
    </div>
  )
}

/* ── The KPI card ─────────────────────────────────────────────────────────── */

const TILE_TONE = {
  accent: 'bg-accent-soft text-accent',
  good: 'bg-good/10 text-good',
  warn: 'bg-warn/10 text-warn',
  bad: 'bg-bad/10 text-bad',
} as const

/**
 * One headline number, its label and its change.
 *
 * Ported from their `KpiCard`, minus the sparkline: the trend chart below says
 * the same thing with an axis, and a 38-pixel line with no scale is decoration.
 *
 * `invertDelta` is load-bearing — more breaches is not good news, and without
 * it that card turns green in the week somebody shouted at four customers.
 */
function KpiCard({
  icon: Icon,
  label,
  value,
  suffix,
  delta,
  invertDelta = false,
  hint,
  tone = 'accent',
}: {
  icon: LucideIcon
  label: string
  value: string | null
  suffix?: string
  delta?: string | null
  invertDelta?: boolean
  hint?: string
  tone?: keyof typeof TILE_TONE
}) {
  const deltaValue = toNumber(delta)
  const good = deltaIsGood(deltaValue, invertDelta)

  return (
    <Card className="flex h-full flex-col p-4">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            'inline-flex size-10 shrink-0 items-center justify-center rounded-md',
            TILE_TONE[tone],
          )}
        >
          <Icon className="size-4" aria-hidden />
        </span>

        <div className="min-w-0 flex-1">
          <p className="flex items-baseline gap-1.5">
            <span className="font-mono text-2xl font-semibold tabular-nums text-text">
              {value ?? EM_DASH}
            </span>
            {suffix && value !== null ? (
              <span className="text-xs text-muted">{suffix}</span>
            ) : null}
          </p>
          {/* One line, truncated: a long label wrapping makes its card taller
              than the three beside it and breaks the row. */}
          <p className="mt-1 truncate text-xs text-muted" title={label}>
            {label}
          </p>
        </div>

        {deltaValue !== null ? (
          <Badge tone={good === null ? 'neutral' : good ? 'good' : 'bad'}>
            {deltaValue > 0 ? '+' : ''}
            {delta}%
          </Badge>
        ) : null}
      </div>

      {hint ? <p className="mt-2 text-2xs leading-snug text-muted">{hint}</p> : null}
    </Card>
  )
}

/**
 * The call-type strip: a row, not a card.
 *
 * **This is the line that stops the headline reading as lost data.** The KPI
 * above counts SCORED conversations, and an internal call or one with no
 * recording is never scored — so in a month of 22,000 calls the card can read
 * "6" while nothing at all is wrong. Measured in BonviZvonki: 72 against
 * 22,026, with the page next door reporting 21,513 for the same period.
 *
 * A row rather than a fifth card, deliberately: these are not targets. Putting
 * "internal calls" in the KPI row invites somebody to try to reduce it, and an
 * internal call is also work.
 */
function CallTypeStrip({ overview }: { overview: AnalyticsOverview }) {
  const counts = overview.call_types
  if (overview.calls_total === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-md bg-surface-2 px-3 py-2">
      <span className="text-2xs font-medium text-muted">
        {t('analytics.byType', { count: formatCount(overview.calls_total) })}
      </span>
      {CALL_TYPE_ORDER.filter((key) => counts[key] > 0).map((key) => (
        <span key={key} className="flex items-center gap-1.5 text-2xs">
          <span
            className={cn(
              'size-1.5 rounded-full',
              key === 'external' ? 'bg-good' : 'bg-muted',
            )}
            aria-hidden
          />
          <span className="text-muted">{t(CALL_TYPE_LABEL[key])}</span>
          <span className="font-mono font-semibold tabular-nums text-text">
            {formatCount(counts[key])}
          </span>
        </span>
      ))}
    </div>
  )
}

/* ── The page ─────────────────────────────────────────────────────────────── */

export function AnalyticsPage() {
  const can = useAuth((state) => state.can)
  // `analysis:read` is held by `admin` and `manager`, and both hold
  // `agents:read` — the column and its filter follow the roster permission
  // because that is what fills the dropdown.
  const showAgent = can(Perm.AGENTS_READ)

  const [searchParams, setSearchParams] = useSearchParams()
  const days = parseDays(searchParams.get(PARAM_DAYS))
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const agentId = searchParams.get(PARAM_AGENT) ?? undefined
  const callType = parseEnum(searchParams.get(PARAM_CALL_TYPE), CALL_TYPE_LABEL)
  const bucket = parseEnum<Bucket>(searchParams.get(PARAM_BUCKET), BUCKET_LABEL) ?? 'day'

  const params: AnalyticsQuery = {
    days,
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    // A repeated parameter on the wire: the server declares `list[UUID]`, and a
    // comma-joined string would be a 422.
    ...(agentId ? { agent_id: [agentId] } : {}),
    ...(callType ? { call_type: callType } : {}),
  }

  const overviewQuery = useOverview(params)
  const trendQuery = useTimeseries(params, bucket)
  const rankingQuery = useAgentRanking(params)
  const blocksQuery = useBlockBreakdown(params)
  const flagsQuery = useRedFlagBreakdown(params)
  const distributionQuery = useScoreDistribution(params)
  const agentsQuery = useAgentDirectory(showAgent)

  const filtered = FILTER_PARAMS.some((param) => searchParams.get(param) !== null)

  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setSearchParams(next, { replace: true })
  }

  // The window the SERVER resolved, never one computed here: "last 30 days" is
  // decided in Asia/Tashkent, and a caption from the browser's clock would name
  // a period the numbers were not measured over. A bare ISO date parses as UTC
  // midnight and `formatDate` renders in Asia/Tashkent (UTC+5), so the day is
  // preserved rather than shifted.
  const resolved = overviewQuery.data
  const windowLabel = resolved
    ? t('analytics.window', {
        from: formatDate(resolved.date_from),
        to: formatDate(resolved.date_to),
      })
    : undefined

  return (
    <Page>
      <PageHeader
        title={t('page.analytics')}
        description={windowLabel ?? t('analytics.subtitle')}
        actions={
          <Link
            to="/analysis"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ListChecks className="size-4" aria-hidden />
            {t('analytics.openList')}
          </Link>
        }
      />

      <Card className="flex flex-wrap items-end gap-2 p-3">
        {/* The presets come first and are one click. The two date fields
            narrow the window further; the server ignores `days` once both are
            given, so the two controls cannot contradict each other. */}
        <SegmentedControl
          label={t('analytics.filterPeriod')}
          options={PRESETS}
          value={days}
          labelOf={(option) => t(PRESET_LABEL[option] ?? 'analytics.period30')}
          onSelect={(option) => apply({ [PARAM_DAYS]: String(option) })}
        />

        <DateFilter
          label={t('analytics.filterDateFrom')}
          hint={t('analytics.filterDateEmpty')}
          pickLabel={t('analytics.filterDatePickFrom')}
          clearLabel={t('analytics.filterDateClearFrom')}
          value={dateFrom}
          max={dateTo}
          onChange={(value) => apply({ [PARAM_DATE_FROM]: value })}
        />
        <DateFilter
          label={t('analytics.filterDateTo')}
          hint={t('analytics.filterDateEmpty')}
          pickLabel={t('analytics.filterDatePickTo')}
          clearLabel={t('analytics.filterDateClearTo')}
          value={dateTo}
          min={dateFrom}
          onChange={(value) => apply({ [PARAM_DATE_TO]: value })}
        />

        {showAgent ? (
          <FilterField label={t('analytics.filterAgent')}>
            <select
              className={SELECT_CLASS}
              value={agentId ?? ''}
              onChange={(event) => apply({ [PARAM_AGENT]: event.target.value || null })}
            >
              <option value="">{t('analytics.filterAgentAll')}</option>
              {(agentsQuery.data?.items ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.full_name}
                </option>
              ))}
            </select>
          </FilterField>
        ) : null}

        <EnumFilter
          label={t('analytics.filterCallType')}
          allLabel={t('analytics.filterAny')}
          labels={CALL_TYPE_LABEL}
          value={callType}
          onChange={(value) => apply({ [PARAM_CALL_TYPE]: value })}
        />

        {filtered ? (
          <Button
            variant="ghost"
            size="sm"
            className="ms-auto"
            onClick={() => {
              const next = new URLSearchParams(searchParams)
              for (const param of FILTER_PARAMS) next.delete(param)
              setSearchParams(next, { replace: true })
            }}
          >
            <FilterX className="size-4" aria-hidden />
            {t('analytics.filterReset')}
          </Button>
        ) : null}
      </Card>

      {/* ── The KPI row, and the strip that explains it ───────────────── */}
      <QueryBoundary query={overviewQuery} skeletonRows={2}>
        {(overview) => (
          <div className="flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard
                icon={Phone}
                label={t('analytics.kpiCalls')}
                value={formatCount(overview.calls.value)}
                delta={overview.calls.delta_percent}
                hint={
                  overview.calls_total > overview.calls.value
                    ? t('analytics.kpiCallsHint', {
                        total: formatCount(overview.calls_total),
                      })
                    : undefined
                }
              />
              <KpiCard
                icon={TrendingUp}
                label={t('analytics.kpiScore')}
                value={overview.ai_score.value}
                suffix="/ 100"
                delta={overview.ai_score.delta_percent}
                tone="good"
              />
              <KpiCard
                icon={AlertTriangle}
                label={t('analytics.kpiRedFlags')}
                value={formatCount(overview.red_flags.value)}
                delta={overview.red_flags.delta_percent}
                invertDelta
                tone="bad"
              />
              <KpiCard
                icon={Clock}
                label={t('analytics.kpiDuration')}
                value={formatDuration(overview.avg_duration_sec)}
                tone="warn"
              />
            </div>
            <CallTypeStrip overview={overview} />
          </div>
        )}
      </QueryBoundary>

      {/* ── The trend ─────────────────────────────────────────────────── */}
      <Section
        title={t('analytics.trendTitle')}
        description={t('analytics.trendHint')}
        actions={
          <SegmentedControl
            options={BUCKETS}
            value={bucket}
            labelOf={(option) => t(BUCKET_LABEL[option])}
            // The bucket is a view control, not a filter: "clear filters"
            // leaves it alone and the other five reports never see it.
            onSelect={(option) => apply({ [PARAM_BUCKET]: option })}
          />
        }
      >
        <QueryBoundary
          query={trendQuery}
          isEmpty={(data) => data.points.length === 0}
          emptyTitle={t('analytics.emptyTrend')}
          emptyHint={t('analytics.emptyHint')}
          skeletonRows={4}
        >
          {(data) => <TrendChart rows={trendRows(data.points, data.bucket)} />}
        </QueryBoundary>
      </Section>

      {/* ── The three breakdowns ──────────────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-3 lg:items-start">
        <Section
          title={t('analytics.blocksTitle')}
          description={t('analytics.blocksHint')}
        >
          <QueryBoundary
            query={blocksQuery}
            isEmpty={(data) => data.items.length === 0}
            emptyTitle={t('analytics.emptyScores')}
            emptyHint={t('analytics.emptyHint')}
            skeletonRows={3}
          >
            {(data) => <BlocksChart rows={blockRows(data.items, blockLabel)} />}
          </QueryBoundary>
        </Section>

        <Section
          title={t('analytics.distributionTitle')}
          description={t('analytics.distributionHint')}
        >
          <QueryBoundary
            query={distributionQuery}
            isEmpty={(data) => data.scored_calls === 0}
            emptyTitle={t('analytics.emptyScores')}
            emptyHint={t('analytics.emptyHint')}
            skeletonRows={3}
          >
            {(data) => <DistributionChart buckets={data.items} />}
          </QueryBoundary>
        </Section>

        <Section
          title={t('analytics.redFlagsTitle')}
          description={t('analytics.redFlagsHint')}
        >
          <QueryBoundary
            query={flagsQuery}
            isEmpty={(data) => data.items.length === 0}
            // Not the same sentence as "nothing was scored": no breaches at all
            // is good news, and a generic empty box would read as a fault.
            emptyTitle={t('analytics.emptyFlags')}
            emptyHint={t('analytics.emptyFlagsHint')}
            skeletonRows={3}
          >
            {(data) => (
              <RedFlagChart
                rows={data.items.map((row) => ({
                  ...row,
                  label: redFlagLabel(row.type),
                }))}
              />
            )}
          </QueryBoundary>
        </Section>
      </div>

      {/* ── The leaderboard ───────────────────────────────────────────── */}
      <Section
        title={t('analytics.rankingTitle')}
        description={t('analytics.rankingHint')}
      >
        <QueryBoundary
          query={rankingQuery}
          isEmpty={(data) => data.items.length === 0}
          emptyTitle={t('analytics.emptyScores')}
          emptyHint={t('analytics.emptyHint')}
          skeletonRows={5}
        >
          {(data) => <AgentRankingTable rows={data.items} />}
        </QueryBoundary>
      </Section>
    </Page>
  )
}
