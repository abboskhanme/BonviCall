/**
 * `/devices/:installationId` — one phone, in detail.
 *
 * A phone that was bound and never reported answers **404** from
 * `GET /devices/{id}`, because that endpoint reads `device_health` and there
 * is no row. That is a state, not an error, and this page says so: it falls
 * back to the installation record and renders "never connected" rather than
 * the generic "not found" — which would read as "no such device" for the one
 * device somebody is most likely looking up.
 */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, PhoneCall, RefreshCw, ShieldOff } from 'lucide-react'

import { useAgentDirectory, agentNameLookup } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { relativeText } from '@/shared/lib/relativeText'
import { Page, PageHeader } from '@/shared/layout/Page'
import {
  EM_DASH,
  formatBytes,
  formatDateTime,
  formatInstantTitle,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { Field, FieldGrid, Section } from '@/shared/ui/detail'
import { LoadingState, ErrorState } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { RevokeDeviceModal } from './RevokeDeviceModal'
import type { CapabilityState } from './api'
import {
  problemsFor,
  stateFor,
  useCommands,
  useDevice,
  useInstallations,
  useIssueCommand,
  type DeviceDetail,
  type Installation,
} from './api'
import {
  CAPABILITY_LABEL,
  CAPABILITY_STATE_LABEL,
  CAPABILITY_STATE_TONE,
  CAPTURE_ROUTE_LABEL,
  COMMAND_KIND_LABEL,
  COMMAND_STATUS_LABEL,
  COMMAND_STATUS_TONE,
  FLEET_PROBLEM_LABEL,
  FLEET_STATE_LABEL,
  FLEET_STATE_TONE,
  FUNNEL_STAGE_LABEL,
  INSTALLATION_STATUS_LABEL,
  NETWORK_TYPE_LABEL,
  VERIFICATION_METHOD_LABEL,
} from './labels'

function yesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return EM_DASH
  return value ? t('common.yes') : t('common.no')
}

function CommandHistory({ installationId }: { installationId: string }) {
  const commandsQuery = useCommands(installationId)
  const items = commandsQuery.data?.items ?? []

  return (
    <Section title={t('devices.commandsTitle')} description={t('devices.commandsSubtitle')}>
      {items.length === 0 ? (
        <p className="text-sm text-muted">{t('devices.noCommands')}</p>
      ) : (
        <TableWrap>
          <Table>
            <THead>
              <tr>
                <TH>{t('devices.cmdKind')}</TH>
                <TH>{t('devices.cmdStatus')}</TH>
                <TH>{t('devices.cmdCreated')}</TH>
                {/* UC-16 puts a five-second bar on click-to-call, so the
                    latency is stored and shown rather than inferred. */}
                <TH className="text-end">{t('devices.cmdLatency')}</TH>
                <TH>{t('devices.cmdFailure')}</TH>
              </tr>
            </THead>
            <TBody>
              {items.map((command) => (
                <TR key={command.id}>
                  <TD>{t(COMMAND_KIND_LABEL[command.kind])}</TD>
                  <TD>
                    <Badge tone={COMMAND_STATUS_TONE[command.status]}>
                      {t(COMMAND_STATUS_LABEL[command.status])}
                    </Badge>
                  </TD>
                  <TD
                    className="whitespace-nowrap text-muted"
                    title={formatInstantTitle(command.created_at)}
                  >
                    {formatDateTime(command.created_at)}
                  </TD>
                  <TD className="text-end font-mono tabular-nums text-muted">
                    {command.latency_ms === null ? EM_DASH : `${command.latency_ms} ms`}
                  </TD>
                  <TD className="text-xs text-muted">{command.failure_reason ?? EM_DASH}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </TableWrap>
      )}
    </Section>
  )
}

/**
 * The capability matrix — the question "which permission is missing on this
 * handset" answered without phoning the salesperson.
 *
 * `granted_not_working` is rendered as loudly as `denied`, because that is R3
 * itself: Android reports the permission as granted and an OEM layer refuses
 * it anyway. A matrix that showed it as a shade of "granted" would hide the
 * only state this page was built to catch.
 */
function CapabilityMatrix({ capabilities }: { capabilities: CapabilityState[] }) {
  if (capabilities.length === 0) {
    return (
      <Section title={t('devices.sectionCapabilities')}>
        <p className="text-sm text-muted">{t('devices.noCapabilities')}</p>
      </Section>
    )
  }
  return (
    <Section
      title={t('devices.sectionCapabilities')}
      description={t('devices.capabilitiesSubtitle')}
    >
      <TableWrap>
        <Table>
          <THead>
            <tr>
              <TH>{t('devices.capName')}</TH>
              <TH>{t('devices.capState')}</TH>
              <TH>{t('devices.capChanged')}</TH>
              <TH>{t('devices.capDetail')}</TH>
            </tr>
          </THead>
          <TBody>
            {capabilities.map((capability) => (
              <TR key={capability.capability}>
                <TD>{t(CAPABILITY_LABEL[capability.capability])}</TD>
                <TD>
                  <Badge tone={CAPABILITY_STATE_TONE[capability.state]}>
                    {t(CAPABILITY_STATE_LABEL[capability.state])}
                  </Badge>
                </TD>
                <TD
                  className="whitespace-nowrap text-muted"
                  title={formatInstantTitle(capability.changed_at)}
                >
                  {relativeText(capability.changed_at)}
                </TD>
                <TD className="text-xs text-muted">{capability.detail ?? EM_DASH}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </TableWrap>
    </Section>
  )
}

function DeviceBody({
  installation,
  health,
}: {
  installation: Installation | null
  health: DeviceDetail
}) {
  const can = useAuth((state) => state.can)
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const agentName = agentNameLookup(agentsQuery.data?.items)(health.agent_id)
  const issue = useIssueCommand(health.installation_id)
  const [revoking, setRevoking] = useState(false)

  const stage = installation?.funnel_stage ?? null
  const state = stateFor(health, stage)
  const problems = problemsFor(health, stage)

  return (
    <div className="flex flex-col gap-4">
      <Section
        title={
          `${health.manufacturer ?? ''} ${health.model ?? ''}`.trim() || t('devices.unknownModel')
        }
        description={agentName ?? undefined}
        actions={
          <>
            {can(Perm.SETTINGS_WRITE) ? (
              <Button
                variant="secondary"
                size="sm"
                disabled={issue.status === 'pending'}
                onClick={() => issue.mutate({ kind: 'recheck' })}
              >
                <RefreshCw className="size-3.5" aria-hidden />
                {t('devices.recheck')}
              </Button>
            ) : null}
            {can(Perm.COMMANDS_DIAL) ? (
              <Button
                variant="secondary"
                size="sm"
                disabled={issue.status === 'pending'}
                onClick={() => issue.mutate({ kind: 'ping' })}
              >
                <PhoneCall className="size-3.5" aria-hidden />
                {t('devices.ping')}
              </Button>
            ) : null}
            {can(Perm.INSTALLATIONS_REVOKE) ? (
              <Button variant="ghost" size="sm" onClick={() => setRevoking(true)}>
                <ShieldOff className="size-3.5" aria-hidden />
                {t('devices.revoke')}
              </Button>
            ) : null}
          </>
        }
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={FLEET_STATE_TONE[state]}>{t(FLEET_STATE_LABEL[state])}</Badge>
            <Badge tone="neutral">
              {t(INSTALLATION_STATUS_LABEL[health.installation_status])}
            </Badge>
            {installation ? (
              <Badge tone="neutral">{t(FUNNEL_STAGE_LABEL[installation.funnel_stage])}</Badge>
            ) : null}
            {/* `capturing` is the server's own answer to "is this phone
                actually recording right now", and it is the one line an admin
                came to the page for. */}
            {health.capturing !== undefined && health.capturing !== null ? (
              <Badge tone={health.capturing ? 'good' : 'bad'}>
                {t(health.capturing ? 'devices.capturingYes' : 'devices.capturingNo')}
              </Badge>
            ) : null}
            {agentName ? (
              <Link
                to={`/agents/${health.agent_id}`}
                className="text-xs text-accent underline-offset-2 hover:underline"
              >
                {t('devices.openAgent')}
              </Link>
            ) : null}
          </div>

          {problems.length > 0 ? (
            <ul className="flex flex-wrap gap-1">
              {problems.map((problem) => (
                <li key={problem}>
                  <Badge tone="warn">{t(FLEET_PROBLEM_LABEL[problem])}</Badge>
                </li>
              ))}
            </ul>
          ) : null}

          {issue.error ? (
            <p className="text-xs text-bad">{messageForError(issue.error)}</p>
          ) : null}
        </div>
      </Section>

      {health.never_reported ? (
        /* Bound and never heard from. The server answers 200 with this flag
           now rather than 404, so the page can say what happened instead of
           implying the device does not exist. */
        <Card className="border-bad/40 bg-bad/5 p-4">
          <p className="text-sm font-medium text-text">{t('devices.neverReportedTitle')}</p>
          <p className="mt-1 text-xs text-muted">{t('devices.neverReportedHint')}</p>
        </Card>
      ) : (
        <>
          <Section title={t('devices.sectionCapture')}>
            <FieldGrid>
              <Field
                label={t('devices.colRoute')}
                value={
                  health.recording_route ? t(CAPTURE_ROUTE_LABEL[health.recording_route]) : null
                }
              />
              <Field label={t('devices.routeOk')} value={yesNo(health.recording_route_ok)} />
              <Field label={t('devices.captureEnabled')} value={yesNo(health.capture_enabled)} />
              <Field label={t('devices.serviceRunning')} value={yesNo(health.service_running)} />
              <Field
                label={t('devices.batteryExempt')}
                value={yesNo(health.battery_optimisation_exempt)}
              />
              <Field label={t('devices.powerSave')} value={yesNo(health.power_save_mode)} />
            </FieldGrid>
          </Section>

          <Section title={t('devices.sectionQueue')}>
            <FieldGrid>
              <Field
                label={t('devices.queueRecords')}
                value={String(health.queue_records ?? 0)}
              />
              <Field label={t('devices.queueBytes')} value={formatBytes(health.queue_bytes)} />
              <Field
                label={t('devices.queueOldest')}
                value={health.queue_oldest_at ? relativeText(health.queue_oldest_at) : null}
                title={
                  health.queue_oldest_at ? formatInstantTitle(health.queue_oldest_at) : undefined
                }
              />
              {/* Parked, never deleted (N8): five failed attempts and the
                  record waits for a human rather than disappearing. */}
              <Field label={t('devices.parked')} value={String(health.parked_records ?? 0)} />
              <Field
                label={t('devices.freeStorage')}
                value={formatBytes(health.free_storage_bytes)}
              />
              <Field
                label={t('devices.cellularMonth')}
                value={formatBytes(health.cellular_bytes_month)}
              />
            </FieldGrid>
          </Section>

          <Section title={t('devices.sectionDevice')}>
            <FieldGrid>
              <Field
                label={t('devices.colLastSeen')}
                value={health.last_heartbeat_at ? relativeText(health.last_heartbeat_at) : null}
                title={
                  health.last_heartbeat_at
                    ? formatInstantTitle(health.last_heartbeat_at)
                    : undefined
                }
              />
              <Field
                label={t('devices.lastCall')}
                value={health.last_call_at ? relativeText(health.last_call_at) : null}
              />
              <Field
                label={t('devices.colAppVersion')}
                value={
                  health.app_version
                    ? `${health.app_version}${health.app_variant ? ` · ${health.app_variant}` : ''}`
                    : null
                }
              />
              <Field
                label={t('devices.android')}
                value={
                  health.android_release
                    ? `${health.android_release}${health.api_level ? ` (API ${health.api_level})` : ''}`
                    : null
                }
              />
              <Field
                label={t('devices.battery')}
                value={
                  health.battery_level === null || health.battery_level === undefined
                    ? null
                    : `${health.battery_level}%${health.battery_charging ? ' ⚡' : ''}`
                }
              />
              <Field
                label={t('devices.network')}
                value={health.network_type ? t(NETWORK_TYPE_LABEL[health.network_type]) : null}
              />
              <Field
                label={t('devices.clockSkew')}
                value={
                  health.clock_skew_sec === null || health.clock_skew_sec === undefined
                    ? null
                    : t('callDetail.clockSkewValue', { seconds: health.clock_skew_sec })
                }
              />
              <Field label={t('devices.timezone')} value={health.device_timezone} />
              <Field
                label={t('agentDetail.verification')}
                value={
                  installation?.verification_method
                    ? t(VERIFICATION_METHOD_LABEL[installation.verification_method])
                    : null
                }
              />
            </FieldGrid>
          </Section>
        </>
      )}

      <CapabilityMatrix capabilities={health.capabilities ?? []} />

      <CommandHistory installationId={health.installation_id} />

      {can(Perm.INSTALLATIONS_REVOKE) ? (
        <RevokeDeviceModal
          open={revoking}
          onOpenChange={setRevoking}
          installationId={health.installation_id}
        />
      ) : null}
    </div>
  )
}

export function DeviceDetailPage() {
  const { installationId } = useParams<{ installationId: string }>()
  const deviceQuery = useDevice(installationId)
  const installationsQuery = useInstallations()

  const installation =
    installationsQuery.data?.items.find((item) => item.id === installationId) ?? null

  // Both queries settle before anything renders: the device 404 is meaningful
  // only once we know whether the installation exists.
  const settled = deviceQuery.status !== 'pending' && installationsQuery.status !== 'pending'

  return (
    <Page>
      <PageHeader
        title={t('page.deviceDetail')}
        actions={
          <Link
            to="/devices"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t('devices.back')}
          </Link>
        }
      />

      {!settled ? (
        <LoadingState rows={6} />
      ) : deviceQuery.data === undefined ? (
        <ErrorState error={deviceQuery.error} onRetry={() => void deviceQuery.refetch()} />
      ) : (
        <DeviceBody installation={installation} health={deviceQuery.data} />
      )}
    </Page>
  )
}
