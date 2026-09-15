/**
 * `/` — the dashboard. Deliberately small.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Every tile is gated by a permission that appears in
 * `DASHBOARD_PERMISSIONS`** (`shared/auth/landing.ts`), and a test asserts
 * that in both directions. This is not bookkeeping: that list is what decides
 * where a user lands after logging in, so a tile rendered outside it puts a
 * 403 on somebody's first screen — the one page they cannot navigate away
 * from a mistake on.
 *
 * The rule this page follows is that a tile is a QUESTION with a number and a
 * way through to the answer. A number with no route is trivia; the tile links
 * to the page that explains it (SPEC §5.2).
 *
 * It reuses the queries the destination pages already own rather than adding
 * dashboard-only endpoints, so a figure here and the list behind it cannot
 * disagree.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BellRing, FileWarning, Home, Phone, Smartphone } from 'lucide-react'

import { useAlerts } from '@/modules/alerts/api'
import { ALERT_SEVERITY_LABEL, ALERT_SEVERITY_TONE } from '@/modules/alerts/routing'
import { useAuth } from '@/modules/auth/store'
import {
  buildFleet,
  needsAttention,
  supersededInstallationIds,
  useDevices,
  useInstallations,
} from '@/modules/devices/api'
import { FLEET_STATE_LABEL } from '@/modules/devices/labels'
import { useCallStats } from '@/modules/calls/api'
import { CallFlowChart } from './CallFlowChart'
import { isoDateLabel } from './chart'
import {
  PERIODS,
  PERIOD_LABEL,
  isComplete,
  useDashboardPeriod,
  usePeriodWindow,
  type PeriodControl,
  type PeriodSelection,
} from './period'
import { useGapReport } from './api'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount } from '@/shared/lib/format'
import { Badge, Card } from '@/shared/ui/primitives'
import { buttonClasses } from '@/shared/ui/buttonStyles'
import { DateFilter } from '@/shared/ui/filters'

function Tile({
  icon,
  label,
  value,
  hint,
  to,
  children,
}: {
  icon: ReactNode
  label: string
  value: string
  hint?: string
  to: string
  children?: ReactNode
}) {
  return (
    <Card className="p-4">
      <Link to={to} className="group block">
        <div className="flex items-center gap-2 text-muted">
          {icon}
          <span className="text-2xs font-medium uppercase tracking-wide">{label}</span>
        </div>
        <p className="mt-2 text-3xl font-semibold text-text group-hover:text-accent">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
      </Link>
      {children ? <div className="mt-3 flex flex-wrap gap-1">{children}</div> : null}
    </Card>
  )
}

/**
 * Calls in the chosen period. `calls:read` or `calls:read:own` — the server
 * narrows the rows, so a salesperson sees their own count.
 *
 * It counts the chart's own buckets rather than asking `/calls` for a total:
 * one request, and the headline and the line drawn under it are then the same
 * arithmetic on the same rows. A tile that disagreed with the chart beside it
 * would be the first thing anybody noticed.
 */
function CallsTile({ selection }: { selection: PeriodSelection }) {
  const query = useCallStats(selection)
  // Nothing while a custom range is half-chosen: the query still holds the
  // previous window's answer (`keepPreviousData`), and a count dated to a
  // period the reader has just left is worse than a dash.
  const stats = isComplete(selection) ? query.data : undefined
  const total = stats?.buckets.reduce((sum, bucket) => sum + bucket.total, 0)
  return (
    <Tile
      icon={<Phone className="size-4" aria-hidden />}
      label={t('dashboard.callsInPeriod')}
      value={typeof total === 'number' ? formatCount(total) : EM_DASH}
      hint={
        stats
          ? t('dashboard.chart.range', {
              from: isoDateLabel(stats.date_from),
              to: isoDateLabel(stats.date_to),
            })
          : t(PERIOD_LABEL[selection.period])
      }
      to={
        stats
          ? `/calls?date_from=${stats.date_from}&date_to=${stats.date_to}`
          : '/calls'
      }
    />
  )
}

/** Phones needing attention, not phones total: the number that should move
 *  somebody. `never_reported` is in it, which is the whole point. */
function DevicesTile() {
  const query = useDevices()
  const installations = useInstallations()
  const stageByInstallation = new Map(
    (installations.data?.items ?? []).map((item) => [item.id, item.funnel_stage]),
  )
  const fleet = buildFleet(
    query.data?.items,
    stageByInstallation,
    new Date(),
    supersededInstallationIds(installations.data?.items),
  )
  const problems = fleet.filter((row) => needsAttention(row.state))
  // The two states that need a person to travel, as opposed to a phone that
  // will come back by itself.
  const silent = fleet.filter(
    (row) => row.state === 'never_reported' || row.state === 'install_disappeared',
  )
  return (
    <Tile
      icon={<Smartphone className="size-4" aria-hidden />}
      label={t('dashboard.devicesNeedingAttention')}
      value={query.data ? `${problems.length}/${fleet.length}` : EM_DASH}
      hint={t('dashboard.devicesHint')}
      to="/devices"
    >
      {silent.length > 0 ? (
        <Badge tone="bad">
          {t('dashboard.silentDevices', {
            n: silent.length,
            state: t(FLEET_STATE_LABEL.never_reported),
          })}
        </Badge>
      ) : null}
    </Tile>
  )
}

function AlertsTile() {
  const query = useAlerts({ open_only: true })
  const alerts = query.data?.items ?? []
  const bySeverity = (['critical', 'warning', 'info'] as const).map((severity) => ({
    severity,
    count: alerts.filter((alert) => alert.severity === severity).length,
  }))
  return (
    <Tile
      icon={<BellRing className="size-4" aria-hidden />}
      label={t('dashboard.openAlerts')}
      value={query.data ? formatCount(alerts.length) : EM_DASH}
      hint={t('dashboard.alertsHint')}
      to="/alerts"
    >
      {bySeverity
        .filter((row) => row.count > 0)
        .map((row) => (
          <Badge key={row.severity} tone={ALERT_SEVERITY_TONE[row.severity]}>
            {t(ALERT_SEVERITY_LABEL[row.severity])}: {row.count}
          </Badge>
        ))}
    </Tile>
  )
}

/**
 * Capture rate, which is the one number that says whether the product is
 * doing its job at all — over the chosen period.
 *
 * The window comes from `/calls/stats` rather than from the browser's clock,
 * so "yozib olish darajasi" and the line above it cover the same days. Until
 * it arrives the report is unfiltered: all of time is a true answer to a
 * slightly different question, where a guessed fortnight is a false answer to
 * this one.
 */
function CaptureTile({ selection }: { selection: PeriodSelection }) {
  const window = usePeriodWindow(selection)
  const query = useGapReport(window ?? {})
  const report = query.data
  const range = window ? `&date_from=${window.date_from}&date_to=${window.date_to}` : ''
  return (
    <Tile
      icon={<FileWarning className="size-4" aria-hidden />}
      label={t('dashboard.captureRate')}
      value={report?.capture_rate ? `${report.capture_rate}%` : EM_DASH}
      hint={
        report
          ? t('dashboard.captureHint', { n: formatCount(report.missing_total) })
          : t('dashboard.captureHintEmpty')
      }
      // `/reports/gap` was removed on 2026-09-14; the same question is the
      // calls list filtered to the recordings that are missing.
      to={`/calls?has_audio=false${range}`}
    />
  )
}

/**
 * Hafta / oy / yil / o'z davri. It governs the whole page, so it sits in the
 * header rather than on the chart.
 *
 * The two date fields appear only under `custom`, and picking either one
 * selects `custom` — so the reader who reaches for a date does not have to
 * press a mode button first, and the three presets stay one click away.
 */
function PeriodTabs({ control }: { control: PeriodControl }) {
  const { selection, setPeriod, setBound } = control
  return (
    <div className="flex flex-wrap items-end justify-end gap-2">
      <div className="flex rounded-md border border-border bg-surface p-0.5" role="group">
        {PERIODS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setPeriod(option)}
            aria-pressed={option === selection.period}
            className={cn(
              'rounded-sm px-3 py-1 text-xs font-medium transition-colors',
              option === selection.period
                ? 'bg-accent-soft text-accent'
                : 'text-muted hover:text-text',
            )}
          >
            {t(PERIOD_LABEL[option])}
          </button>
        ))}
      </div>

      {selection.period === 'custom' ? (
        <div className="flex flex-wrap items-end gap-2">
          {/* The calls list's own two bounds, reused rather than re-invented:
              the same control, the same words, and the same cross-constraint
              so the picker cannot offer a backwards range. */}
          <DateFilter
            label={t('calls.filterDateFrom')}
            hint={t('calls.filterDateEmpty')}
            pickLabel={t('calls.filterDatePickFrom')}
            clearLabel={t('calls.filterDateClearFrom')}
            value={selection.date_from}
            max={selection.date_to}
            onChange={(value) => setBound('date_from', value)}
          />
          <DateFilter
            label={t('calls.filterDateTo')}
            hint={t('calls.filterDateEmpty')}
            pickLabel={t('calls.filterDatePickTo')}
            clearLabel={t('calls.filterDateClearTo')}
            value={selection.date_to}
            min={selection.date_from}
            onChange={(value) => setBound('date_to', value)}
          />
        </div>
      ) : null}
    </div>
  )
}

export function DashboardPage() {
  const can = useAuth((state) => state.can)
  const user = useAuth((state) => state.user)
  const periodControl = useDashboardPeriod()
  const selection = periodControl.selection

  // Each tile is shown only for a permission listed in DASHBOARD_PERMISSIONS.
  // `dashboard.tiles.test.tsx` asserts the two lists agree.
  const showCalls = can(Perm.CALLS_READ) || can(Perm.CALLS_READ_OWN)
  const showDevices = can(Perm.DEVICES_READ) || can(Perm.DEVICES_READ_OWN)
  const showAlerts = can(Perm.ALERTS_READ)
  const showReports = can(Perm.REPORTS_READ)
  const nothingToShow = !showCalls && !showDevices && !showAlerts && !showReports

  return (
    <Page>
      <PageHeader
        title={t('page.dashboard')}
        description={user ? t('dashboard.greeting', { name: user.full_name }) : undefined}
        // In the header rather than on the chart, because it is not the
        // chart's control: the two date-based tiles read the same window.
        actions={
          <div className="flex flex-wrap items-end justify-end gap-2">
            {/* The public front page, which is where the APK is handed out
                (SPEC §4.1 rule 5). An admin showing somebody the product, or
                reinstalling after a factory reset, reaches it from here rather
                than by typing the address — it is outside the AppShell, so the
                menu cannot carry it. */}
            <Link to="/" className={buttonClasses({ variant: 'secondary', size: 'sm' })}>
              <Home className="size-4" aria-hidden />
              {t('dashboard.openLanding')}
            </Link>
            {showCalls || showReports ? <PeriodTabs control={periodControl} /> : null}
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {showCalls ? <CallsTile selection={selection} /> : null}
        {/* Fleet state and open alerts are "right now" questions and ignore
            the period on purpose — there is no useful reading of "phones that
            were silent last March", and filtering them by date would invent
            one. */}
        {showDevices ? <DevicesTile /> : null}
        {showAlerts ? <AlertsTile /> : null}
        {showReports ? <CaptureTile selection={selection} /> : null}
      </div>

      {/* The tiles answer "how are we right now"; the chart answers "and is
          that normal" — the same permission, because it is the same rows
          (`calls:read` / `calls:read:own`, narrowed server-side). */}
      {showCalls ? <CallFlowChart selection={selection} /> : null}

      {nothingToShow ? (
        // Reachable only if the permission registry gains a role with none of
        // DASHBOARD_PERMISSIONS. Saying so beats an empty page that looks broken.
        <Card className="p-10 text-center">
          <p className="text-sm text-muted">{t('dashboard.nothingToShow')}</p>
        </Card>
      ) : null}
    </Page>
  )
}
