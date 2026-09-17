/**
 * `/activity` — call activity: volume and answerability.
 *
 * Ported from BonviZvonki `web/src/modules/activity/ActivityPage.tsx`.
 *
 * Three layers, in this order on purpose: choose the window → the company's
 * figures → the table of employees. A manager looks at the overall state first
 * and only then at who is behind it.
 *
 * ⚠️ THE TERMS ARE KEPT APART. There is no single "unanswered" column:
 *
 *   · "Xodim ko'tarmadi" = INCOMING unanswered. A customer called and the
 *     company did not pick up. Our responsibility.
 *   · "Mijoz ko'tarmadi" = OUTGOING unanswered. The customer did not pick up.
 *
 * Putting them in one column doubles the figure and blames the employee for
 * half of it (measured over 7 days: 983 and 1047).
 *
 * Scope: a `sales` user reaches this page through `calls:read:own` and the
 * SERVER narrows the rows. This page does not re-implement that rule — it only
 * hides the agent filter, which is presentation, not access control
 * (CONVENTIONS-CLIENT.md §2, CONVENTIONS.md §11).
 *
 * Loading, empty and error are `QueryBoundary`'s, not this page's.
 */
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowDownLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  PhoneMissed,
  Sheet as SheetIcon,
  UserX,
} from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount } from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { DateFilter, FilterField, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { ActivityChart } from './ActivityChart'
import { COLUMNS, sortRows, type SortOrder } from './columns'
import { MissedClientsModal } from './MissedClientsModal'
import {
  HOURLY_BELOW_DAYS,
  PERIODS,
  PERIOD_LABEL,
  useActivity,
  type ActivityQuery,
  type ActivityReport,
  type ActivityRow,
  type Period,
} from './api'
import { exportActivity } from './export'
import { t } from '@/shared/i18n'
import { defaultHidden, type SeriesKey } from './series'

/** The URL is the screen state (CONVENTIONS-CLIENT.md §2), and the parameter
 *  names are the server's own — so a window somebody wants to show a colleague
 *  is a link they can paste. */
const PARAM_DAYS = 'days'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'
const PARAM_AGENT = 'agent_id'
const PARAM_SORT = 'sort'
const PARAM_ORDER = 'order'

function SortableTH({
  label,
  active,
  order,
  onSort,
  onExplain,
  className,
}: {
  label: string
  active: boolean
  order: SortOrder
  onSort: () => void
  onExplain: () => void
  className?: string
}) {
  const Icon = active ? (order === 'asc' ? ChevronUp : ChevronDown) : null
  return (
    <TH className={className}>
      <button
        type="button"
        className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide hover:text-text"
        onClick={() => {
          onSort()
          // Pressing also opens the explanation. On a touchscreen there is no
          // hover, and without this the tips would be unreachable from a phone.
          onExplain()
        }}
        onMouseEnter={onExplain}
        aria-pressed={active}
      >
        <span>{label}</span>
        {Icon ? <Icon className="size-3" aria-hidden /> : null}
      </button>
    </TH>
  )
}

function MetricCard({
  icon,
  label,
  hint,
  value,
  sub,
  tone,
}: {
  icon: React.ReactNode
  label: string
  hint: string
  value: number
  sub?: string
  tone?: 'good' | 'bad'
}) {
  return (
    // Labelled, because three of the four cards deliberately carry the SAME
    // words as a column of the table below them — "Xodim ko'tarmadi" is one
    // metric shown twice, and a reader who could not tell the two apart would
    // read them as two. The group name gives the card an identity a screen
    // reader announces and a test can address.
    <Card className="p-4" role="group" aria-label={label}>
      <div className="flex items-start gap-3">
        <span
          className={cn(
            'grid size-9 shrink-0 place-items-center rounded-md',
            tone === 'bad' && 'bg-bad/10 text-bad',
            tone === 'good' && 'bg-good/10 text-good',
            !tone && 'bg-accent-soft text-accent',
          )}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-2xs font-medium text-muted">{label}</div>
          <div className="text-2xl font-semibold leading-tight tabular-nums text-text">
            {formatCount(value)}
          </div>
          {sub ? <div className="mt-0.5 text-2xs text-muted">{sub}</div> : null}
        </div>
      </div>
      <p className="mt-2.5 text-2xs leading-relaxed text-muted">{hint}</p>
    </Card>
  )
}

function Metrics({ report }: { report: ActivityReport }) {
  const total = report.total
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        icon={<ArrowUpRight className="size-4" aria-hidden />}
        label={t('activity.outbound')}
        hint={t('activity.outboundHint')}
        value={total.outbound_total}
        sub={t('activity.answeredOf', {
          count: total.outbound_answered,
          total: total.outbound_total,
        })}
      />
      <MetricCard
        icon={<ArrowDownLeft className="size-4" aria-hidden />}
        label={t('activity.inbound')}
        hint={t('activity.inboundHint')}
        value={total.inbound_total}
        sub={t('activity.answeredOf', {
          count: total.inbound_answered,
          total: total.inbound_total,
        })}
      />
      <MetricCard
        icon={<PhoneMissed className="size-4" aria-hidden />}
        label={t('activity.missed')}
        hint={t('activity.missedHint')}
        value={total.missed}
        tone="bad"
        sub={
          total.missed_rate === null
            ? undefined
            : t('activity.ofInbound', { percent: total.missed_rate })
        }
      />
      {/* ⚠️ THE HEADLINE CARD, and it counts PEOPLE. The event count says how
          much volume there was; this says how many HUMAN BEINGS could not
          reach us and were never called back. Lost business is measured in
          people. */}
      <MetricCard
        icon={<UserX className="size-4" aria-hidden />}
        label={t('activity.unreached')}
        hint={t('activity.unreachedHint', { hours: report.callback_window_hours })}
        value={total.clients_unreached}
        tone={total.clients_unreached > 0 ? 'bad' : 'good'}
        sub={
          total.callback_rate === null
            ? undefined
            : t('activity.unreachedSub', {
                reached: total.clients_reached,
                clients: total.missed_clients,
                percent: total.callback_rate,
              })
        }
      />
    </div>
  )
}

export function ActivityPage() {
  const can = useAuth((state) => state.can)
  // Full `calls:read` sees everybody; `calls:read:own` sees one agent — their
  // own — so the filter and the agent column would be one repeated name.
  const fleetWide = can(Perm.CALLS_READ)

  const [searchParams, setSearchParams] = useSearchParams()
  const rawDays = Number(searchParams.get(PARAM_DAYS))
  const days: Period = (PERIODS as readonly number[]).includes(rawDays)
    ? (rawDays as Period)
    : 7
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const agentId = searchParams.get(PARAM_AGENT) ?? undefined
  const sortField = searchParams.get(PARAM_SORT)
  const sortOrder: SortOrder = searchParams.get(PARAM_ORDER) === 'asc' ? 'asc' : 'desc'

  const query: ActivityQuery = useMemo(
    () => ({
      days,
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
      // `agent_id` is a repeated parameter on the wire; the picker chooses one.
      ...(agentId ? { agent_id: [agentId] } : {}),
    }),
    [days, dateFrom, dateTo, agentId],
  )

  const activity = useActivity(query)
  const agents = useAgentDirectory(fleetWide && can(Perm.AGENTS_READ))

  const [hidden, setHidden] = useState<ReadonlySet<SeriesKey>>(defaultHidden)
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(null)
  const [explained, setExplained] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportFailed, setExportFailed] = useState(false)

  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setSearchParams(next, { replace: true })
  }

  function toggleSeries(key: SeriesKey) {
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function sortBy(field: string) {
    // A number sorts DESCENDING first: the question is "who has the most
    // missed calls", not the fewest.
    const order = sortField === field && sortOrder === 'desc' ? 'asc' : 'desc'
    apply({ [PARAM_SORT]: field, [PARAM_ORDER]: order })
  }

  /**
   * Write the file from what is ON SCREEN.
   *
   * No second request: one would run at a different moment and the file could
   * carry different numbers from the page it was exported from. The rows go in
   * the reader's own sort order for the same reason.
   */
  async function runExport(report: ActivityReport, rows: ActivityRow[], byHour: boolean) {
    if (exporting) return
    setExporting(true)
    setExportFailed(false)
    try {
      await exportActivity({ report: { ...report, agents: rows }, byHour, hidden })
    } catch {
      // The cause tells the reader nothing (the chunk failed to load, the tab
      // ran out of memory). What matters is that it does not fail silently: a
      // button that does nothing gets pressed again and again.
      setExportFailed(true)
    } finally {
      setExporting(false)
    }
  }

  return (
    <Page>
      <PageHeader
        title={t('activity.title')}
        description={fleetWide ? t('activity.subtitle') : t('activity.ownScopeNote')}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              title={t('activity.export.hint')}
              // Nothing to export until the report arrives: an empty file is
              // indistinguishable from a broken button.
              disabled={!activity.data?.agents.length || exporting}
              onClick={() => {
                const report = activity.data
                if (!report) return
                const byHour = report.days <= HOURLY_BELOW_DAYS
                void runExport(report, sortRows(report.agents, sortField, sortOrder), byHour)
              }}
            >
              <SheetIcon className="size-4" aria-hidden />
              {exporting ? t('activity.export.running') : t('activity.export.button')}
            </Button>

            <div className="flex rounded-md border border-border bg-surface p-0.5" role="group">
              {PERIODS.map((period) => (
                <button
                  key={period}
                  type="button"
                  aria-pressed={period === days && !dateFrom && !dateTo}
                  className={cn(
                    'rounded-sm px-3 py-1 text-xs font-medium transition-colors',
                    period === days && !dateFrom && !dateTo
                      ? 'bg-accent-soft text-accent'
                      : 'text-muted hover:text-text',
                  )}
                  // An explicit range WINS over `days` on the server, so
                  // pressing a period button has to clear it — otherwise
                  // nothing changes and the reader reads that as a fault.
                  onClick={() =>
                    apply({
                      [PARAM_DAYS]: String(period),
                      [PARAM_DATE_FROM]: null,
                      [PARAM_DATE_TO]: null,
                    })
                  }
                >
                  {t(PERIOD_LABEL[period])}
                </button>
              ))}
            </div>
          </div>
        }
      />

      {exportFailed ? (
        <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad" role="alert">
          {t('activity.export.failed')}
        </p>
      ) : null}

      <Card className="flex flex-wrap items-end gap-2 p-3">
        {fleetWide ? (
          <FilterField label={t('activity.colAgent')}>
            <select
              className={SELECT_CLASS}
              value={agentId ?? ''}
              onChange={(event) => apply({ [PARAM_AGENT]: event.target.value || null })}
            >
              <option value="">{t('calls.filterAgentAll')}</option>
              {(agents.data?.items ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.full_name}
                </option>
              ))}
            </select>
          </FilterField>
        ) : null}

        {/* Asia/Tashkent calendar dates, inclusive on both ends, exactly as the
            calls list writes them — one control, one behaviour. */}
        <DateFilter
          label={t('calls.filterDateFrom')}
          hint={t('calls.filterDateEmpty')}
          pickLabel={t('calls.filterDatePickFrom')}
          clearLabel={t('calls.filterDateClearFrom')}
          value={dateFrom}
          max={dateTo}
          onChange={(value) => apply({ [PARAM_DATE_FROM]: value })}
        />
        <DateFilter
          label={t('calls.filterDateTo')}
          hint={t('calls.filterDateEmpty')}
          pickLabel={t('calls.filterDatePickTo')}
          clearLabel={t('calls.filterDateClearTo')}
          value={dateTo}
          min={dateFrom}
          onChange={(value) => apply({ [PARAM_DATE_TO]: value })}
        />
      </Card>

      <QueryBoundary
        query={activity}
        isEmpty={(report) => report.agents.length === 0}
        emptyTitle={t('activity.emptyTitle')}
        emptyHint={t('activity.emptyHint')}
        skeletonRows={6}
      >
        {(report) => {
          /* The cut follows the SERVER's `days`, not the button that was
             pressed: an explicit range wins server-side, so the two can
             disagree and the axis must follow the data that came back. */
          const byHour = report.days <= HOURLY_BELOW_DAYS
          const rows = sortRows(report.agents, sortField, sortOrder)
          const total = report.total

          return (
            <>
              <Metrics report={report} />

              {report.callback_median_minutes !== null ? (
                <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
                  {t('activity.medianNote', {
                    minutes: report.callback_median_minutes,
                    hours: report.callback_window_hours,
                  })}
                </p>
              ) : null}

              <Card className="p-4">
                <p className="text-2xs font-medium uppercase tracking-wide text-muted">
                  {byHour ? t('activity.chartTitleHour') : t('activity.chartTitle')}
                </p>
                <p className="mb-3 mt-1 text-xs text-muted">{t('activity.chartHint')}</p>
                <ActivityChart
                  days={report.days_series}
                  hours={report.hours_series}
                  byHour={byHour}
                  hidden={hidden}
                  onToggle={toggleSeries}
                />
              </Card>

              <Card className="p-4">
                <p className="text-2xs font-medium uppercase tracking-wide text-muted">
                  {fleetWide ? t('activity.byAgent') : t('activity.myRow')}
                </p>
                {/* The column explanation sits OUTSIDE the table, which scrolls
                    horizontally and would clip a native tooltip. A fixed slot,
                    so nothing jumps when one appears. */}
                <p
                  className={cn(
                    'mt-1 min-h-[2.6rem] text-2xs leading-relaxed transition-colors',
                    explained ? 'font-medium text-text' : 'text-muted',
                  )}
                >
                  {explained
                    ? t(
                        COLUMNS.find((column) => column.key === explained)?.tip ??
                          'activity.byAgentHint',
                        { hours: report.callback_window_hours },
                      )
                    : t('activity.byAgentHint')}
                </p>
              </Card>

              <TableWrap>
                <Table>
                  <THead>
                    <tr>
                      <TH>{t('activity.colAgent')}</TH>
                      {COLUMNS.map((column) => (
                        <SortableTH
                          key={column.key}
                          label={t(column.label)}
                          active={sortField === column.key}
                          order={sortOrder}
                          onSort={() => sortBy(column.key)}
                          onExplain={() => setExplained(column.key)}
                          className="text-end"
                        />
                      ))}
                    </tr>
                  </THead>
                  <TBody>
                    {rows.map((row) => {
                      // Nothing to show for an employee with no missed
                      // customers, so no way in either.
                      const openable = row.missed_clients > 0
                      return (
                        <TR
                          key={row.agent_id}
                          interactive={openable}
                          tabIndex={openable ? 0 : undefined}
                          onClick={
                            openable
                              ? () => setPicked({ id: row.agent_id, name: row.agent_name })
                              : undefined
                          }
                          onKeyDown={
                            openable
                              ? (event) => {
                                  if (event.key !== 'Enter' && event.key !== ' ') return
                                  event.preventDefault()
                                  setPicked({ id: row.agent_id, name: row.agent_name })
                                }
                              : undefined
                          }
                        >
                          <TD>
                            <div className="flex items-center gap-2">
                              <span className="truncate font-medium">{row.agent_name}</span>
                              {openable ? (
                                <ChevronRight
                                  className="size-4 shrink-0 text-muted"
                                  aria-label={t('activity.drillOpen')}
                                />
                              ) : null}
                            </div>
                          </TD>
                          {COLUMNS.map((column) => (
                            <TD
                              key={column.key}
                              className={cn(
                                'whitespace-nowrap text-end tabular-nums',
                                column.tone?.(row),
                              )}
                            >
                              {column.render(row)}
                            </TD>
                          ))}
                        </TR>
                      )
                    })}
                  </TBody>
                  {rows.length > 1 ? (
                    <tfoot className="border-t-2 border-border font-semibold">
                      <tr>
                        <TD>{t('activity.totalRow')}</TD>
                        {COLUMNS.map((column) => (
                          <TD
                            key={column.key}
                            className={cn(
                              'whitespace-nowrap text-end tabular-nums',
                              column.tone?.(total),
                            )}
                          >
                            {/* ⚠️ The median is the REPORT's own value, never
                                the average of the employees'. Medians cannot be
                                averaged, and the server computes this one over
                                the calls themselves. */}
                            {column.key === 'median'
                              ? (report.callback_median_minutes ?? EM_DASH)
                              : column.render(total)}
                          </TD>
                        ))}
                      </tr>
                    </tfoot>
                  ) : null}
                </Table>
              </TableWrap>

              {/* Says what the window actually covered, in the server's own
                  words: a period label that disagrees with the data is the
                  first thing somebody spots. */}
              <p className="text-2xs text-muted">
                <Badge tone="neutral">
                  {t('activity.scope', { count: report.agents.length })}
                </Badge>
              </p>
            </>
          )
        }}
      </QueryBoundary>

      <MissedClientsModal
        agentId={picked?.id ?? null}
        agentName={picked?.name ?? ''}
        query={query}
        onClose={() => setPicked(null)}
      />
    </Page>
  )
}
