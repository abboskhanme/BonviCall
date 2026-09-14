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
import { BellRing, FileWarning, Phone, Smartphone } from 'lucide-react'

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
import { useCallsPage } from '@/modules/calls/api'
import { useGapReport } from './api'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { EM_DASH, formatCount } from '@/shared/lib/format'
import { Badge, Card } from '@/shared/ui/primitives'

/** Today, as an Asia/Tashkent calendar date — the same day boundary every
 *  business date in this system uses (D-10). */
function todayInTashkent(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tashkent',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now)
}

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

/** Calls received today. `calls:read` or `calls:read:own` — the server
 *  narrows the rows, so a salesperson sees their own count. */
function CallsTile() {
  const today = todayInTashkent()
  const query = useCallsPage({ date_from: today, date_to: today, with_total: true, limit: 1 })
  const total = query.data?.total
  return (
    <Tile
      icon={<Phone className="size-4" aria-hidden />}
      label={t('dashboard.callsToday')}
      value={typeof total === 'number' ? formatCount(total) : EM_DASH}
      hint={t('dashboard.callsTodayHint')}
      to={`/calls?date_from=${today}&date_to=${today}`}
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

/** Capture rate, which is the one number that says whether the product is
 *  doing its job at all. */
function CaptureTile() {
  const query = useGapReport({})
  const report = query.data
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
      to="/calls?has_audio=false"
    />
  )
}

export function DashboardPage() {
  const can = useAuth((state) => state.can)
  const user = useAuth((state) => state.user)

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
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {showCalls ? <CallsTile /> : null}
        {showDevices ? <DevicesTile /> : null}
        {showAlerts ? <AlertsTile /> : null}
        {showReports ? <CaptureTile /> : null}
      </div>

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
