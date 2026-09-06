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

import {
  buildFleet,
  needsAttention,
  supersededInstallationIds,
  useDevices,
  useInstallations,
  type FleetProblem,
  type FleetRow,
  type FleetState,
} from './api'
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

/**
 * Everything already said by the state badge, removed from the problems list.
 *
 * `Holati` and `Muammolar` used to print the same word twice on most rows —
 * "Aloqada emas" as a status and again as a problem — which is a column
 * carrying no information and a row that takes twice the height to say one
 * thing. The state badge answers "how is it"; this answers "and what else",
 * which is only worth a column when there IS something else.
 */
function extraProblems(row: FleetRow): FleetProblem[] {
  const saidByState: Partial<Record<FleetState, FleetProblem>> = {
    never_reported: 'never_reported',
    install_disappeared: 'install_disappeared',
    offline: 'offline',
    revoked: 'revoked',
  }
  const covered = saidByState[row.state]
  return row.problems.filter((problem) => problem !== covered)
}

/** The queue cell: a count, a size when one is known, and never a dash
 *  standing in for a number the device simply did not send. */
function queueText(health: FleetRow['health']): string {
  if (health.never_reported) return EM_DASH
  const records = health.queue_records ?? 0
  if (records === 0) return t('devices.queueEmpty')
  const bytes = health.queue_bytes
  if (bytes === null || bytes === undefined) return t('devices.queueCountOnly', { n: records })
  return t('devices.queueValue', { n: records, size: formatBytes(bytes) })
}

function DeviceRow({ row, agentName }: { row: FleetRow; agentName: (id: string) => string | null }) {
  const { health, state } = row
  const name = agentName(health.agent_id)
  const extra = extraProblems(row)

  return (
    <TR>
      <TD className="whitespace-nowrap">
        <Link
          to={`/devices/${health.installation_id}`}
          className="font-medium text-text underline-offset-2 hover:text-accent hover:underline"
        >
          {`${health.manufacturer ?? ''} ${health.model ?? ''}`.trim() || t('devices.unknownModel')}
        </Link>
      </TD>
      <TD className="whitespace-nowrap">
        {name ? (
          <Link
            to={`/agents/${health.agent_id}`}
            className="text-text underline-offset-2 hover:text-accent hover:underline"
          >
            {name}
          </Link>
        ) : (
          <span className="font-mono text-xs text-muted">{shortId(health.agent_id)}</span>
        )}
      </TD>
      <TD className="whitespace-nowrap">
        {/* `whitespace-nowrap` on the cell: the badge wrapped onto two lines
            and took the whole row with it. */}
        <Badge tone={FLEET_STATE_TONE[state]}>{t(FLEET_STATE_LABEL[state])}</Badge>
      </TD>
      <TD
        className="whitespace-nowrap text-muted"
        title={health.last_heartbeat_at ? formatInstantTitle(health.last_heartbeat_at) : undefined}
      >
        {/* Never-reported has no timestamp, and a dash would say "unknown"
            when the truth is "never". */}
        {health.last_heartbeat_at ? relativeText(health.last_heartbeat_at) : t('devices.never')}
      </TD>
      <TD className="whitespace-nowrap">
        {health.recording_route ? (
          <span className={health.recording_route_ok === false ? 'text-bad' : 'text-text'}>
            {t(CAPTURE_ROUTE_LABEL[health.recording_route])}
          </span>
        ) : (
          EM_DASH
        )}
      </TD>
      <TD
        className="whitespace-nowrap text-end font-mono tabular-nums text-muted"
        title={health.never_reported ? undefined : t('devices.colQueueHint')}
      >
        {/* Was `0 · —`, which said nothing twice. An empty queue is the
            normal, good case and reads as one; a queue with records names its
            size ONLY when a size is known — the device does not always report
            `queue_bytes`, and `1 ta · —` is the same non-answer in a
            different place. */}
        {queueText(health)}
      </TD>
      <TD className="whitespace-nowrap text-muted">{health.app_version ?? EM_DASH}</TD>
      <TD>
        {extra.length === 0 ? (
          <span className="text-xs text-muted">{EM_DASH}</span>
        ) : (
          <ul className="flex flex-wrap gap-1">
            {extra.map((problem) => (
              <li key={problem}>
                <Badge tone="warn">{t(FLEET_PROBLEM_LABEL[problem])}</Badge>
              </li>
            ))}
          </ul>
        )}
      </TD>
    </TR>
  )
}

export function DevicesPage() {
  const can = useAuth((state) => state.can)
  const [searchParams, setSearchParams] = useSearchParams()
  const stateFilter = parseState(searchParams.get(PARAM_STATE))

  const devicesQuery = useDevices()
  // The server's own `install_disappeared` stage outranks our silence
  // heuristic: it sees an uninstall the panel could only guess at.
  const installationsQuery = useInstallations()
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const agentName = agentNameLookup(agentsQuery.data?.items)

  function applyFilter(value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(PARAM_STATE)
    else next.set(PARAM_STATE, value)
    setSearchParams(next, { replace: true })
  }

  // `GET /devices` LEFT OUTER JOINs `device_health` now, so a phone that has
  // never reported arrives here with `never_reported: true` rather than being
  // absent from the response.
  const stageByInstallation = new Map(
    (installationsQuery.data?.items ?? []).map((item) => [item.id, item.funnel_stage]),
  )
  // Attempts a later enrolment on the same line has overtaken. The server
  // marks some `replaced`; the ones that never reported stay `pending`, and
  // the live fleet had fifty-eight of those for two people.
  const superseded = supersededInstallationIds(installationsQuery.data?.items)
  const fleet = buildFleet(devicesQuery.data?.items, stageByInstallation, new Date(), superseded)
  /**
   * History is not the default view.
   *
   * A real rollout leaves abandoned attempts behind — one salesperson's own
   * list reached 142 rows, of which a handful were live phones. They are
   * still reachable through the state filter; they are just not what the page
   * opens on.
   */
  const hidden = stateFilter ? 0 : fleet.filter((row) => row.state === 'superseded').length
  const visible = stateFilter
    ? fleet.filter((row) => row.state === stateFilter)
    : fleet.filter((row) => row.state !== 'superseded')
  const needAttention = fleet.filter((row) => needsAttention(row.state))
  // `buildFleet` already sorts worst first, so the head of that list IS the
  // worst thing in the fleet.
  const worst = needAttention[0] ?? null
  // Past half, naming one is not triage any more.
  const mostlyBroken = fleet.length > 0 && needAttention.length > fleet.length / 2
  const attentionBreakdown = [...new Set(needAttention.map((row) => row.state))]
    .map(
      (state) =>
        `${needAttention.filter((row) => row.state === state).length} ${t(FLEET_STATE_LABEL[state])}`,
    )
    .join(', ')

  return (
    <Page>
      <PageHeader title={t('page.devices')} description={t('devices.subtitle')} />

      {worst ? (
        /* Naming the single worst thing beats "5 of 5 need attention" — but
           only while "worst" means something. Once most of the fleet is
           flagged, one name out of eleven is the same noise wearing a
           different sentence, so it counts by state instead. */
        <Card className="flex items-start gap-3 border-warn/40 bg-warn/5 p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <p className="text-sm text-text">
            {mostlyBroken
              ? t('devices.attentionMany', {
                  n: needAttention.length,
                  total: fleet.length,
                  breakdown: attentionBreakdown,
                })
              : t('devices.attentionWorst', {
                  state: t(FLEET_STATE_LABEL[worst.state]),
                  device:
                    `${worst.health.manufacturer ?? ''} ${worst.health.model ?? ''}`.trim() ||
                    t('devices.unknownModel'),
                  agent: agentName(worst.health.agent_id) ?? '',
                  more: needAttention.length - 1,
                })}
          </p>
        </Card>
      ) : null}

      {/* One control does not need a card around it. */}
      <div className="flex flex-wrap items-end gap-3">
        <EnumFilter
          label={t('devices.filterState')}
          allLabel={t('calls.filterAny')}
          labels={FLEET_STATE_LABEL}
          value={stateFilter}
          onChange={applyFilter}
        />
        <span className="pb-2 text-xs text-muted">
          {t('devices.total', { count: visible.length })}
          {hidden > 0 ? ` · ${t('devices.hiddenSuperseded', { n: hidden })}` : ''}
        </span>
      </div>

      <QueryBoundary
        query={devicesQuery}
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
                    <DeviceRow key={row.health.installation_id} row={row} agentName={agentName} />
                  ))}
                </TBody>
              </Table>
            </TableWrap>
          </>
        )}
      </QueryBoundary>
    </Page>
  )
}
