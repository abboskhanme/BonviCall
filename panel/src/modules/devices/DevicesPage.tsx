/**
 * `/devices` — fleet health. **Absence is the signal.**
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * R3 is an OEM battery manager killing the capture service silently. The
 * failure never announces itself: a phone simply stops saying anything, and
 * every call it makes from then on is lost. This page exists so a human sees
 * that before the month's gap report does.
 *
 * Two consequences run through everything below.
 *
 * **The default order serves the problem, not the alphabet.** Worst first:
 * never reported, then offline, then degraded, then revoked, then healthy —
 * and within a state, longest-unheard-from first. A fleet page sorted by name
 * makes the one broken phone out of fifteen exactly as prominent as the
 * fourteen working ones, which is the same as not having the page.
 *
 * **A phone that never reported is a row, not a gap.** `GET /devices`
 * inner-joins `device_health`, so an installation bound and never heard from
 * is missing from that response entirely and `GET /devices/{id}` 404s for it.
 * That is the most alarming device in the fleet, so `buildFleet` merges
 * `GET /installations` over the top and gives it its own state.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'

import { useAgentDirectory, agentNameLookup } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { relativeText } from '@/shared/lib/relativeText'
import { Page, PageHeader } from '@/shared/layout/Page'
import {
  EM_DASH,
  formatBytes,
  formatInstantTitle,
  shortId,
} from '@/shared/lib/format'
import { Badge, Card } from '@/shared/ui/primitives'
import { EnumFilter } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { buildFleet, useDevices, useInstallations, type FleetRow, type FleetState } from './api'
import {
  CAPTURE_ROUTE_LABEL,
  FLEET_PROBLEM_LABEL,
  FLEET_STATE_LABEL,
  FLEET_STATE_TONE,
} from './labels'

const PARAM_STATE = 'state'

/** A pasted `?state=sideways` is no filter rather than a crash. */
function parseState(raw: string | null): FleetState | undefined {
  return raw !== null && raw in FLEET_STATE_LABEL ? (raw as FleetState) : undefined
}

function DeviceRow({ row, agentName }: { row: FleetRow; agentName: (id: string) => string | null }) {
  const { installation, health, state, problems } = row
  const name = agentName(installation.agent_id)

  return (
    <TR>
      <TD className="whitespace-nowrap">
        <Link
          to={`/devices/${installation.id}`}
          className="font-medium text-text underline-offset-2 hover:text-accent hover:underline"
        >
          {health ? `${health.manufacturer ?? ''} ${health.model ?? ''}`.trim() || t('devices.unknownModel') : t('devices.unknownModel')}
        </Link>
      </TD>
      <TD className="whitespace-nowrap">
        {name ? (
          <Link
            to={`/agents/${installation.agent_id}`}
            className="text-text underline-offset-2 hover:text-accent hover:underline"
          >
            {name}
          </Link>
        ) : (
          <span className="font-mono text-xs text-muted">{shortId(installation.agent_id)}</span>
        )}
      </TD>
      <TD>
        <Badge tone={FLEET_STATE_TONE[state]}>{t(FLEET_STATE_LABEL[state])}</Badge>
      </TD>
      <TD
        className="whitespace-nowrap text-muted"
        title={health?.last_heartbeat_at ? formatInstantTitle(health.last_heartbeat_at) : undefined}
      >
        {/* Never-reported has no timestamp to show, and rendering a dash here
            would say "unknown" when the truth is "never". */}
        {health?.last_heartbeat_at ? relativeText(health.last_heartbeat_at) : t('devices.never')}
      </TD>
      <TD className="whitespace-nowrap">
        {health?.recording_route ? (
          <span className={health.recording_route_ok === false ? 'text-bad' : 'text-text'}>
            {t(CAPTURE_ROUTE_LABEL[health.recording_route])}
          </span>
        ) : (
          EM_DASH
        )}
      </TD>
      <TD className="whitespace-nowrap text-end font-mono tabular-nums text-muted">
        {health ? `${health.queue_records ?? 0} · ${formatBytes(health.queue_bytes)}` : EM_DASH}
      </TD>
      <TD className="whitespace-nowrap text-muted">{health?.app_version ?? EM_DASH}</TD>
      <TD>
        <ul className="flex flex-wrap gap-1">
          {problems.map((problem) => (
            <li key={problem}>
              <Badge tone="warn">{t(FLEET_PROBLEM_LABEL[problem])}</Badge>
            </li>
          ))}
        </ul>
      </TD>
    </TR>
  )
}

export function DevicesPage() {
  const can = useAuth((state) => state.can)
  const [searchParams, setSearchParams] = useSearchParams()
  const stateFilter = parseState(searchParams.get(PARAM_STATE))

  const installationsQuery = useInstallations()
  const devicesQuery = useDevices()
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const agentName = agentNameLookup(agentsQuery.data?.items)

  function applyFilter(value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(PARAM_STATE)
    else next.set(PARAM_STATE, value)
    setSearchParams(next, { replace: true })
  }

  // The list is driven by INSTALLATIONS, so a phone with no telemetry still
  // appears. `useDevices` only decorates it.
  const fleet = buildFleet(installationsQuery.data?.items, devicesQuery.data?.items)
  const visible = stateFilter ? fleet.filter((row) => row.state === stateFilter) : fleet
  const needAttention = fleet.filter((row) => row.state !== 'healthy' && row.state !== 'revoked')

  return (
    <Page>
      <PageHeader title={t('page.devices')} description={t('devices.subtitle')} />

      {needAttention.length > 0 ? (
        <Card className="flex items-start gap-3 border-warn/40 bg-warn/5 p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <p className="text-sm text-text">
            {t('devices.attention', { n: needAttention.length, total: fleet.length })}
          </p>
        </Card>
      ) : null}

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <EnumFilter
          label={t('devices.filterState')}
          allLabel={t('calls.filterAny')}
          labels={FLEET_STATE_LABEL}
          value={stateFilter}
          onChange={applyFilter}
        />
      </Card>

      <QueryBoundary
        query={installationsQuery}
        isEmpty={() => visible.length === 0}
        emptyTitle={stateFilter ? t('devices.emptyFiltered') : t('devices.emptyAll')}
        emptyHint={stateFilter ? t('devices.emptyFilteredHint') : t('devices.emptyAllHint')}
        skeletonRows={6}
      >
        {() => (
          <>
            <TableWrap>
              <Table>
                <THead>
                  <tr>
                    <TH>{t('devices.colDevice')}</TH>
                    <TH>{t('devices.colAgent')}</TH>
                    <TH>{t('devices.colState')}</TH>
                    <TH title={t('devices.colLastSeenHint')}>{t('devices.colLastSeen')}</TH>
                    <TH>{t('devices.colRoute')}</TH>
                    <TH className="text-end">{t('devices.colQueue')}</TH>
                    <TH>{t('devices.colAppVersion')}</TH>
                    <TH>{t('devices.colProblems')}</TH>
                  </tr>
                </THead>
                <TBody>
                  {visible.map((row) => (
                    <DeviceRow key={row.installation.id} row={row} agentName={agentName} />
                  ))}
                </TBody>
              </Table>
            </TableWrap>
            <p className="text-xs text-muted">{t('devices.total', { count: visible.length })}</p>
          </>
        )}
      </QueryBoundary>
    </Page>
  )
}
