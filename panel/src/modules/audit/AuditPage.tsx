/**
 * `/audit` — who did what, to which object, when, and from where.
 *
 * Read-only, and deliberately without a single delete or edit affordance
 * anywhere on the page (SPEC §5.2). Admin only, because `audit:read` is.
 *
 * `detail` carries before/after values and counts and is rendered as raw
 * key=value pairs: it never contains a password, a token or a code (the
 * server's redaction filter guarantees that, N26), and its keys are English
 * identifiers because this row is evidence for whoever is investigating, not
 * prose for a general reader.
 *
 * **`audio_play` and `audio_download` are the rows this page exists for**
 * (UC-24). Exactly one `audio_play` is written per playback start — a seek
 * does not add another — so this list answers "who listened to this call"
 * rather than "how many times did somebody drag the scrubber".
 */
import { useSearchParams } from 'react-router-dom'

import { agentNameLookup, useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { EM_DASH, formatDateTime, formatInstantTitle, shortId } from '@/shared/lib/format'
import { Badge, Card } from '@/shared/ui/primitives'
import { EnumFilter } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { useAudit, type AuditEntry } from './api'
import { ACTOR_TYPE_LABEL, AUDIT_ACTION_LABEL, AUDIT_ACTION_TONE } from './labels'

const PARAM_ACTION = 'action'

type AuditAction = AuditEntry['action']

function parseAction(raw: string | null): AuditAction | undefined {
  return raw !== null && raw in AUDIT_ACTION_LABEL ? (raw as AuditAction) : undefined
}

/** English keys on purpose: this is evidence, not prose. Never a secret — the
 *  server's redaction filter strips tokens and passwords before they land. */
function Detail({ detail }: { detail: Record<string, unknown> | null | undefined }) {
  if (!detail) return <>{EM_DASH}</>
  const entries = Object.entries(detail)
  if (entries.length === 0) return <>{EM_DASH}</>
  return (
    <span className="font-mono text-2xs text-muted">
      {entries.map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
    </span>
  )
}

export function AuditPage() {
  const can = useAuth((state) => state.can)
  const [searchParams, setSearchParams] = useSearchParams()
  const action = parseAction(searchParams.get(PARAM_ACTION))

  const auditQuery = useAudit({ limit: 200, ...(action ? { action } : {}) })
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const agentName = agentNameLookup(agentsQuery.data?.items)

  function applyFilter(value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(PARAM_ACTION)
    else next.set(PARAM_ACTION, value)
    setSearchParams(next, { replace: true })
  }

  return (
    <Page>
      <PageHeader title={t('page.audit')} description={t('audit.subtitle')} />

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <EnumFilter
          label={t('audit.filterAction')}
          allLabel={t('calls.filterAny')}
          labels={AUDIT_ACTION_LABEL}
          value={action}
          onChange={applyFilter}
        />
      </Card>

      <QueryBoundary
        query={auditQuery}
        isEmpty={(data) => data.items.length === 0}
        emptyTitle={action ? t('audit.emptyFiltered') : t('audit.emptyAll')}
        emptyHint={action ? t('audit.emptyFilteredHint') : t('audit.emptyAllHint')}
        skeletonRows={8}
      >
        {(data) => (
          <TableWrap>
            <Table>
              <THead>
                <tr>
                  <TH>{t('audit.colAt')}</TH>
                  <TH>{t('audit.colActor')}</TH>
                  <TH>{t('audit.colAction')}</TH>
                  <TH>{t('audit.colObject')}</TH>
                  <TH>{t('audit.colDetail')}</TH>
                  <TH>{t('audit.colIp')}</TH>
                </tr>
              </THead>
              <TBody>
                {data.items.map((entry) => {
                  const tone = AUDIT_ACTION_TONE[entry.action]
                  return (
                    <TR key={entry.id}>
                      <TD
                        className="whitespace-nowrap text-muted"
                        title={formatInstantTitle(entry.at)}
                      >
                        {formatDateTime(entry.at)}
                      </TD>
                      <TD className="whitespace-nowrap">
                        <span className="text-text">{t(ACTOR_TYPE_LABEL[entry.actor_type])}</span>
                        {entry.actor_user_id ? (
                          <span className="ms-2 font-mono text-2xs text-muted">
                            {agentName(entry.actor_user_id) ?? shortId(entry.actor_user_id)}
                          </span>
                        ) : null}
                      </TD>
                      <TD>
                        {tone ? (
                          <Badge tone={tone}>{t(AUDIT_ACTION_LABEL[entry.action])}</Badge>
                        ) : (
                          t(AUDIT_ACTION_LABEL[entry.action])
                        )}
                      </TD>
                      <TD className="whitespace-nowrap text-xs text-muted">
                        {entry.object_type}
                        {entry.object_id ? ` · ${shortId(entry.object_id)}` : ''}
                      </TD>
                      <TD className="max-w-md truncate">
                        <Detail detail={entry.detail as Record<string, unknown> | null} />
                      </TD>
                      <TD className="whitespace-nowrap font-mono text-2xs text-muted">
                        {entry.ip ?? EM_DASH}
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </QueryBoundary>
    </Page>
  )
}
