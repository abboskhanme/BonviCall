/**
 * `/alerts` — where R3 and R17 become visible to a human.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **An alert nobody acts on is worse than no alert**, because it trains people
 * to scroll past the next one. Every row therefore answers four questions
 * without being clicked:
 *
 *   what it is    — `title_uz`, derived server-side from `kind`
 *   what to do    — `body_uz`, one sentence, the next action
 *   who it is about — the agent, by name, linked
 *   when          — first seen, last seen, and how many times
 *
 * And a way through: to the device, or to the agent, whichever can actually
 * fix it. `ALERT_TARGET` decides, because a link to a phone is a dead end for
 * a storage or receiver alert.
 *
 * Repeats bump `occurrence_count` rather than inserting rows, so a phone that
 * has been offline for a week is one line, not a thousand.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { Link, useSearchParams } from 'react-router-dom'
import { BellOff, Check } from 'lucide-react'

import { agentNameLookup, useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { formatCount, formatDateTime, formatInstantTitle } from '@/shared/lib/format'
import { relativeText } from '@/shared/lib/relativeText'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { EnumFilter, FilterField, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import { useAcknowledgeAlert, useAlerts, type Alert } from './api'
import {
  ALERT_SEVERITY_LABEL,
  ALERT_SEVERITY_ORDER,
  ALERT_SEVERITY_TONE,
  ALERT_TARGET,
  isFirstObservation,
  type AlertSeverity,
} from './routing'

const PARAM_SEVERITY = 'severity'
const PARAM_OPEN = 'open'

function parseSeverity(raw: string | null): AlertSeverity | undefined {
  return raw !== null && raw in ALERT_SEVERITY_LABEL ? (raw as AlertSeverity) : undefined
}

/**
 * The machine-readable half of the envelope, shown small.
 *
 * The keys are English identifiers — `offline_minutes`, `never_reported` — and
 * they stay that way on purpose: this is a build artefact for whoever is
 * diagnosing, in the same spirit as a task id, not a sentence anybody is meant
 * to read as prose. The Uzbek sentence above it is what the page is for.
 */
function AlertDetail({ detail }: { detail: Record<string, unknown> | null }) {
  if (!detail) return null
  const entries = Object.entries(detail)
  if (entries.length === 0) return null
  return (
    <p className="mt-1 font-mono text-2xs text-muted">
      {entries.map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
    </p>
  )
}

function AlertRow({ alert, agentName }: { alert: Alert; agentName: (id: string) => string | null }) {
  const can = useAuth((state) => state.can)
  const acknowledge = useAcknowledgeAlert()
  const mayAck = can(Perm.ALERTS_ACK)
  const target = ALERT_TARGET[alert.kind]
  const name = alert.agent_id ? agentName(alert.agent_id) : null
  const detail = alert.detail as Record<string, unknown> | null
  // A phone that arrived already broken never LOST anything, so wording that
  // asserts a change would send an admin hunting for one that never happened.
  const firstObservation = isFirstObservation(detail)

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start gap-3">
        <Badge tone={ALERT_SEVERITY_TONE[alert.severity]}>
          {t(ALERT_SEVERITY_LABEL[alert.severity])}
        </Badge>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-text">
            {/* Derived from `kind` server-side, out of this panel's own Uzbek,
                so the two cannot disagree. */}
            {alert.title_uz}
          </p>
          {/* The next action. Without this the page is a list of nouns. */}
          {alert.body_uz ? <p className="mt-1 text-sm text-muted">{alert.body_uz}</p> : null}
          {firstObservation ? (
            <p className="mt-1 text-xs text-warn">{t('alerts.firstObservation')}</p>
          ) : null}
          <AlertDetail detail={detail} />

          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
            {name ? (
              <Link
                to={`/agents/${alert.agent_id}`}
                className="text-accent underline-offset-2 hover:underline"
              >
                {name}
              </Link>
            ) : null}
            {alert.device_model ? <span>{alert.device_model}</span> : null}
            <span title={formatInstantTitle(alert.last_seen_at)}>
              {t('alerts.lastSeen', { when: relativeText(alert.last_seen_at) })}
            </span>
            <span title={formatInstantTitle(alert.first_seen_at)}>
              {t('alerts.firstSeen', { at: formatDateTime(alert.first_seen_at) })}
            </span>
            {/* Repeats bump the count instead of adding rows, so this number
                is how long it has been going on. */}
            {alert.occurrence_count > 1 ? (
              <span>{t('alerts.occurrences', { n: formatCount(alert.occurrence_count) })}</span>
            ) : null}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {target === 'device' && alert.installation_id ? (
            <Link
              to={`/devices/${alert.installation_id}`}
              className="text-xs text-accent underline-offset-2 hover:underline"
            >
              {t('alerts.openDevice')}
            </Link>
          ) : null}
          {target === 'agent' && alert.agent_id ? (
            <Link
              to={`/agents/${alert.agent_id}`}
              className="text-xs text-accent underline-offset-2 hover:underline"
            >
              {t('alerts.openAgent')}
            </Link>
          ) : null}

          {alert.acknowledged_at ? (
            <Badge tone="neutral">{t('alerts.acknowledged')}</Badge>
          ) : mayAck ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={acknowledge.status === 'pending'}
              onClick={() => acknowledge.mutate(alert.id)}
            >
              <Check className="size-3.5" aria-hidden />
              {t('alerts.acknowledge')}
            </Button>
          ) : null}
        </div>
      </div>

      {acknowledge.error ? (
        <p className="mt-2 text-xs text-bad">{messageForError(acknowledge.error)}</p>
      ) : null}
    </Card>
  )
}

export function AlertsPage() {
  const can = useAuth((state) => state.can)
  const [searchParams, setSearchParams] = useSearchParams()
  const severity = parseSeverity(searchParams.get(PARAM_SEVERITY))
  // Open-only by default: the inbox is a to-do list, not an archive.
  const openOnly = searchParams.get(PARAM_OPEN) !== 'all'

  const alertsQuery = useAlerts({
    open_only: openOnly,
    ...(severity ? { severity } : {}),
  })
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const agentName = agentNameLookup(agentsQuery.data?.items)

  function applyFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setSearchParams(next, { replace: true })
  }

  // Worst first. Within a severity, most recently seen first: an alert still
  // firing matters more than one that stopped an hour ago.
  const alerts = [...(alertsQuery.data?.items ?? [])].sort((a, b) => {
    const bySeverity = ALERT_SEVERITY_ORDER[a.severity] - ALERT_SEVERITY_ORDER[b.severity]
    if (bySeverity !== 0) return bySeverity
    return b.last_seen_at.localeCompare(a.last_seen_at)
  })

  const critical = alerts.filter((alert) => alert.severity === 'critical').length

  return (
    <Page>
      <PageHeader title={t('page.alerts')} description={t('alerts.subtitle')} />

      {critical > 0 ? (
        <Card className="flex items-center gap-3 border-bad/40 bg-bad/5 p-3">
          <BellOff className="size-4 shrink-0 text-bad" aria-hidden />
          <p className="text-sm text-text">{t('alerts.criticalCount', { n: critical })}</p>
        </Card>
      ) : null}

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <EnumFilter
          label={t('alerts.filterSeverity')}
          allLabel={t('calls.filterAny')}
          labels={ALERT_SEVERITY_LABEL}
          value={severity}
          onChange={(value) => applyFilter(PARAM_SEVERITY, value)}
        />
        <FilterField label={t('alerts.filterState')}>
          <select
            className={SELECT_CLASS}
            value={openOnly ? 'open' : 'all'}
            onChange={(event) =>
              applyFilter(PARAM_OPEN, event.target.value === 'all' ? 'all' : null)
            }
          >
            <option value="open">{t('alerts.filterOpen')}</option>
            <option value="all">{t('alerts.filterAll')}</option>
          </select>
        </FilterField>
      </Card>

      <QueryBoundary
        query={alertsQuery}
        isEmpty={() => alerts.length === 0}
        // "Nothing is wrong" is genuinely good news and should read that way,
        // rather than as the same grey box every empty list shows.
        emptyTitle={severity || !openOnly ? t('alerts.emptyFiltered') : t('alerts.emptyAll')}
        emptyHint={severity || !openOnly ? t('alerts.emptyFilteredHint') : t('alerts.emptyAllHint')}
        skeletonRows={4}
      >
        {() => (
          <div className="flex flex-col gap-3">
            {alerts.map((alert) => (
              <AlertRow key={alert.id} alert={alert} agentName={agentName} />
            ))}
          </div>
        )}
      </QueryBoundary>
    </Page>
  )
}
