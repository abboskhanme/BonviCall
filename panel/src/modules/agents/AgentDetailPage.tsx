/**
 * `/agents/:id` — **the page the rollout runs on.**
 *
 * After `/enrolment` and `/numbers` were removed on 2026-09-05, this page owns
 * the whole of getting one salesperson onto the system. For a fifteen-person
 * team, registering a line and issuing a code are things you do *to a person*,
 * so they happen here rather than in two more top-level sections.
 *
 * It answers, for one agent, in one place:
 *
 *   • who they are and whether they are still active;
 *   • which work number is theirs, **with the assignment history**, because
 *     the mapping is time-boxed and calls before a handover belong to the
 *     previous holder;
 *   • how far through enrolment they are and, if stuck, at which step;
 *   • issue or revoke their enrolment code — the action that starts
 *     everything, and which had no home in the UI at all before this;
 *   • their phone's health, with a link through to the device page.
 *
 * The sections are ordered by what an admin opening this page is most likely
 * to be trying to do: chase somebody who has not finished enrolling.
 */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Archive, Pencil, Smartphone } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import {
  buildFleet,
  supersededInstallationIds,
  useDevices,
  useInstallations,
} from '@/modules/devices/api'
import {
  FLEET_PROBLEM_LABEL,
  FLEET_STATE_LABEL,
  FLEET_STATE_TONE,
  INSTALLATION_STATUS_LABEL,
  VERIFICATION_METHOD_LABEL,
} from '@/modules/devices/labels'
import { agentAssignmentRows, useAgentAssignments, useNumbers } from '@/modules/numbers/api'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { relativeText } from '@/shared/lib/relativeText'
import { Page, PageHeader } from '@/shared/layout/Page'
import { formatInstantTitle } from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { Field, FieldGrid, Section } from '@/shared/ui/detail'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import { AgentModal } from './AgentModal'
import { AlertHistorySection } from './AlertHistorySection'
import { ArchiveAgentModal } from './ArchiveAgentModal'
import { EnrolmentSection } from './EnrolmentSection'
import { NumberSection } from './NumberSection'
import { useAgent, type Agent } from './api'

function DeviceSection({ agentId }: { agentId: string }) {
  const can = useAuth((state) => state.can)
  const mayRead = can(Perm.DEVICES_READ) || can(Perm.DEVICES_READ_OWN)
  const devicesQuery = useDevices()
  const installationsQuery = useInstallations(mayRead ? { agentId } : undefined)

  if (!mayRead) return null

  // `/devices` carries `never_reported` now, so a phone that was bound and
  // never spoke arrives in this list rather than being absent from it.
  const installationById = new Map(
    (installationsQuery.data?.items ?? []).map((item) => [item.id, item]),
  )
  const stageByInstallation = new Map(
    (installationsQuery.data?.items ?? []).map((item) => [item.id, item.funnel_stage]),
  )
  const everyDevice = buildFleet(
    devicesQuery.data?.items,
    stageByInstallation,
    new Date(),
    supersededInstallationIds(installationsQuery.data?.items),
  ).filter((row) => row.health.agent_id === agentId)

  /**
   * The phone this person is using, and only that one.
   *
   * ═══════════════════════════════════════════════════════════════════════
   * A rollout retries: one agent on the live fleet had twenty installations,
   * and every one of them rendered a card here. The list was long enough to
   * hide the only row anybody opens this page for — the handset in their
   * pocket right now.
   *
   * NEWEST, not `status === 'active'`, and that distinction already cost this
   * page once (see `AgentCard` below, which states it at length): an old
   * verified installation outranks the phone that is stuck at a permission
   * screen this morning, so picking "active" shows the wrong one precisely
   * when somebody is looking for the right one.
   *
   * Sorted by the installation's `created_at` rather than by last heartbeat,
   * because a new phone that has never reported is still the current phone.
   * The older ones are counted, not silently discarded — twenty attempts
   * behind one salesperson is the story, even when only one is shown.
   * ═══════════════════════════════════════════════════════════════════════
   */
  const createdAt = new Map(
    (installationsQuery.data?.items ?? []).map((item) => [item.id, item.created_at]),
  )
  const newestFirst = [...everyDevice].sort((a, b) =>
    (createdAt.get(b.health.installation_id) ?? '').localeCompare(
      createdAt.get(a.health.installation_id) ?? '',
    ),
  )
  const fleet = newestFirst.slice(0, 1)
  const olderDevices = Math.max(0, newestFirst.length - 1)

  return (
    <Section title={t('agentDetail.deviceTitle')} description={t('agentDetail.deviceSubtitle')}>
      {fleet.length === 0 ? (
        <p className="text-sm text-muted">{t('agentDetail.noDevice')}</p>
      ) : (
        <div className="space-y-3">
          {fleet.map(({ health, state, problems }) => {
            const installation = installationById.get(health.installation_id)
            return (
              <div key={health.installation_id} className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Smartphone className="size-4 shrink-0 text-muted" aria-hidden />
                  <span className="text-sm font-medium text-text">
                    {`${health.manufacturer ?? ''} ${health.model ?? ''}`.trim() ||
                      t('devices.unknownModel')}
                  </span>
                  <Badge tone={FLEET_STATE_TONE[state]}>{t(FLEET_STATE_LABEL[state])}</Badge>
                  <Badge tone="neutral">
                    {t(INSTALLATION_STATUS_LABEL[health.installation_status])}
                  </Badge>
                  <Link
                    to={`/devices/${health.installation_id}`}
                    className="ms-auto text-xs text-accent underline-offset-2 hover:underline"
                  >
                    {t('agentDetail.openDevice')}
                  </Link>
                </div>

                <FieldGrid className="mt-3">
                  <Field
                    label={t('devices.colLastSeen')}
                    value={
                      health.last_heartbeat_at
                        ? relativeText(health.last_heartbeat_at)
                        : t('devices.never')
                    }
                    title={
                      health.last_heartbeat_at
                        ? formatInstantTitle(health.last_heartbeat_at)
                        : undefined
                    }
                  />
                  <Field label={t('devices.colAppVersion')} value={health.app_version} />
                  <Field label={t('agentDetail.verification')}>
                    {installation?.verification_method ? (
                      <Badge
                        tone={
                          installation.verification_method === 'admin_attested' ? 'warn' : 'good'
                        }
                      >
                        {t(VERIFICATION_METHOD_LABEL[installation.verification_method])}
                      </Badge>
                    ) : null}
                  </Field>
                </FieldGrid>

                {problems.length > 0 ? (
                  <ul className="mt-3 flex flex-wrap gap-1">
                    {problems.map((problem) => (
                      <li key={problem}>
                        <Badge tone="warn">{t(FLEET_PROBLEM_LABEL[problem])}</Badge>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            )
          })}
          {olderDevices > 0 ? (
            <p className="text-2xs text-muted">
              {t('agentDetail.olderDevices', { n: olderDevices })}
            </p>
          ) : null}
        </div>
      )}
    </Section>
  )
}

function AgentCard({ agent }: { agent: Agent }) {
  const can = useAuth((state) => state.can)
  const mayWrite = can(Perm.AGENTS_WRITE)
  const mayArchive = can(Perm.AGENTS_ARCHIVE)
  const mayReadNumbers = can(Perm.NUMBERS_READ)
  const mayReadEnrolment = can(Perm.ENROLMENT_READ)

  const [editing, setEditing] = useState(false)
  const [archiving, setArchiving] = useState(false)

  const numbersQuery = useNumbers()
  const assignmentsQuery = useAgentAssignments(mayReadNumbers ? agent.id : undefined)
  const rows = agentAssignmentRows(assignmentsQuery.data?.items, numbersQuery.data?.items)
  const historyFailed = assignmentsQuery.status === 'error' || numbersQuery.status === 'error'
  const openRow = rows.find((row) => row.assignment.valid_to === null) ?? null

  const installationsQuery = useInstallations(
    can(Perm.INSTALLATIONS_READ) ? { agentId: agent.id } : undefined,
  )

  /**
   * The CURRENT attempt, which is the newest one — not the active one.
   *
   * ═════════════════════════════════════════════════════════════════════════
   * This used to pick `status === 'active'`, and on the live fleet that hid
   * the phone the admin was standing next to. A real rollout retries: one
   * agent had twenty installations, an old verified one among them, and the
   * page showed that instead of the handset stuck at `installed` right now.
   * The funnel then reported somebody as finished while they were stuck.
   *
   * Newest-first is what "where is this person up to" means. The older ones
   * are counted so the churn is visible rather than silently discarded.
   * ═════════════════════════════════════════════════════════════════════════
   */
  const installations = [...(installationsQuery.data?.items ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  )
  const installation = installations[0] ?? null
  const olderInstallations = Math.max(0, installations.length - 1)

  return (
    <div className="flex flex-col gap-4">
      <Section
        title={agent.full_name}
        description={agent.employee_code ?? undefined}
        actions={
          <>
            {mayWrite ? (
              <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                <Pencil className="size-3.5" aria-hidden />
                {t('agents.edit')}
              </Button>
            ) : null}
            {mayArchive && !agent.archived_at ? (
              <Button variant="ghost" size="sm" onClick={() => setArchiving(true)}>
                <Archive className="size-3.5" aria-hidden />
                {t('agents.archive')}
              </Button>
            ) : null}
          </>
        }
      >
        {/* Status alone. The hire date and the free-text note were removed on
            2026-09-14 at the client's request: this card is opened to answer
            "is this person's phone capturing", and neither fact has ever been
            part of that. The columns stay on the server and the import still
            accepts `hired_at` — nothing was dropped from the record, only
            from the screen. */}
        <FieldGrid>
          <Field label={t('agents.colStatus')}>
            {agent.archived_at ? (
              <Badge tone="neutral">{t('agents.statusArchived')}</Badge>
            ) : agent.is_active ? (
              <Badge tone="good">{t('agents.statusActive')}</Badge>
            ) : (
              <Badge tone="warn">{t('agents.statusInactive')}</Badge>
            )}
          </Field>
        </FieldGrid>
      </Section>

      {/* Enrolment first: an admin opening this page is usually chasing
          somebody who has not finished. */}
      {mayReadEnrolment ? (
        <EnrolmentSection
          number={openRow?.number ?? null}
          installation={installation}
          agentName={agent.full_name}
          olderInstallations={olderInstallations}
        />
      ) : null}

      {mayReadNumbers ? (
        <NumberSection agent={agent} rows={rows} loadFailed={historyFailed} />
      ) : null}

      <DeviceSection agentId={agent.id} />

      {/* The closed half of Ogohlantirishlar lives here since
          2026-09-14 — see AlertHistorySection. */}
      {can(Perm.ALERTS_READ) ? <AlertHistorySection agentId={agent.id} /> : null}

      {mayWrite ? (
        <AgentModal open={editing} onOpenChange={setEditing} agent={agent} />
      ) : null}
      {mayArchive ? (
        <ArchiveAgentModal open={archiving} onOpenChange={setArchiving} agent={agent} />
      ) : null}
    </div>
  )
}

export function AgentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const agentQuery = useAgent(id)

  return (
    <Page>
      <PageHeader
        title={t('page.agentDetail')}
        actions={
          <Link
            to="/agents"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t('agentDetail.back')}
          </Link>
        }
      />
      <QueryBoundary query={agentQuery}>{(agent) => <AgentCard agent={agent} />}</QueryBoundary>
    </Page>
  )
}
