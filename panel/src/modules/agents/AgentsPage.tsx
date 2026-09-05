/**
 * `/agents` — the roster (SPEC §5.2).
 *
 * An agent is a salesperson. **It is not a login**, and the create modal says
 * so in one Uzbek line, because "I added Aziz but he cannot sign in" and "I
 * created a user and now there are two Azizes" are the two mistakes this
 * distinction exists to prevent.
 *
 * Archive rather than delete: an agent who has left still owns last year's
 * calls, and the time-boxed assignment history on their card is what keeps
 * those calls attributable. `POST /agents/{id}/archive` answers 409
 * `agent_has_open_assignment` while they still hold a line, and that code
 * carries its own Uzbek sentence.
 */
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Archive, Pencil, Plus } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { EM_DASH, formatDate, formatInstantTitle, formatPhone } from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { FilterField, SELECT_CLASS, TextFilter } from '@/shared/ui/filters'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { useNumbers } from '@/modules/numbers/api'

import { AgentModal } from './AgentModal'
import { CreateAgentModal } from './CreateAgentModal'
import { ArchiveAgentModal } from './ArchiveAgentModal'
import { useAgentLines, useAgents, type Agent } from './api'

const PARAM_Q = 'q'
const PARAM_ARCHIVED = 'archived'

export function AgentsPage() {
  const can = useAuth((state) => state.can)
  const mayWrite = can(Perm.AGENTS_WRITE)
  const mayArchive = can(Perm.AGENTS_ARCHIVE)

  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.get(PARAM_Q) ?? undefined
  const includeArchived = searchParams.get(PARAM_ARCHIVED) === 'true'

  const [editing, setEditing] = useState<Agent | null>(null)
  const [creating, setCreating] = useState(false)
  const [archiving, setArchiving] = useState<Agent | null>(null)

  const agentsQuery = useAgents({ q: search, includeArchived })
  const numbersQuery = useNumbers()
  // The number and the date it was attached: see `useAgentLines` for why this
  // costs one request per agent and what would remove it.
  const { lines, isError: linesFailed } = useAgentLines(
    agentsQuery.data?.items,
    numbersQuery.data?.items,
  )

  function applyFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setSearchParams(next, { replace: true })
  }

  const filtered = search !== undefined || includeArchived

  return (
    <Page>
      <PageHeader
        title={t('page.agents')}
        description={t('agents.subtitle')}
        actions={
          mayWrite ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden />
              {t('agents.create')}
            </Button>
          ) : undefined
        }
      />

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <TextFilter
          label={t('agents.search')}
          placeholder={t('agents.searchHint')}
          value={search}
          onCommit={(value) => applyFilter(PARAM_Q, value)}
        />
        <FilterField label={t('agents.filterArchived')}>
          <select
            className={SELECT_CLASS}
            value={includeArchived ? 'true' : 'false'}
            onChange={(event) =>
              applyFilter(PARAM_ARCHIVED, event.target.value === 'true' ? 'true' : null)
            }
          >
            <option value="false">{t('agents.filterActiveOnly')}</option>
            <option value="true">{t('agents.filterWithArchived')}</option>
          </select>
        </FilterField>
      </Card>

      <QueryBoundary
        query={agentsQuery}
        isEmpty={(data) => data.items.length === 0}
        emptyTitle={filtered ? t('agents.emptyFiltered') : t('agents.emptyAll')}
        emptyHint={filtered ? t('agents.emptyFilteredHint') : t('agents.emptyAllHint')}
        skeletonRows={6}
      >
        {(data) => (
          <>
            <TableWrap>
              <Table>
                <THead>
                  <tr>
                    <TH>{t('agents.colName')}</TH>
                    <TH>{t('agents.colCode')}</TH>
                    <TH>{t('agents.colNumber')}</TH>
                    {/* The date the NUMBER was attached — the assignment's
                        `valid_from`, not the employment date. */}
                    <TH>{t('agents.colAttached')}</TH>
                    <TH>{t('agents.colStatus')}</TH>
                    <TH>{t('agents.colNote')}</TH>
                    {mayWrite || mayArchive ? <TH className="w-0" /> : null}
                  </tr>
                </THead>
                <TBody>
                  {data.items.map((agent) => (
                    <TR key={agent.id}>
                      <TD>
                        <Link
                          to={`/agents/${agent.id}`}
                          className="font-medium text-text underline-offset-2 hover:text-accent hover:underline"
                        >
                          {agent.full_name}
                        </Link>
                      </TD>
                      <TD className="font-mono text-xs text-muted">
                        {agent.employee_code ?? EM_DASH}
                      </TD>
                      <TD className="whitespace-nowrap font-mono">
                        {(() => {
                          const line = lines.get(agent.id)
                          if (!line) return <span className="text-muted">{EM_DASH}</span>
                          return formatPhone(line.e164) ?? line.e164
                        })()}
                      </TD>
                      <TD
                        className="whitespace-nowrap text-muted"
                        title={(() => {
                          const line = lines.get(agent.id)
                          return line ? formatInstantTitle(line.since) : undefined
                        })()}
                      >
                        {(() => {
                          const line = lines.get(agent.id)
                          return line ? formatDate(line.since) : EM_DASH
                        })()}
                      </TD>
                      <TD>
                        {agent.archived_at ? (
                          <Badge tone="neutral">{t('agents.statusArchived')}</Badge>
                        ) : agent.is_active ? (
                          <Badge tone="good">{t('agents.statusActive')}</Badge>
                        ) : (
                          <Badge tone="warn">{t('agents.statusInactive')}</Badge>
                        )}
                      </TD>
                      <TD className="max-w-xs truncate text-xs text-muted" title={agent.note ?? ''}>
                        {agent.note ?? '—'}
                      </TD>
                      {mayWrite || mayArchive ? (
                        <TD>
                          <div className="flex justify-end gap-1">
                            {mayWrite ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={t('agents.edit')}
                                onClick={() => setEditing(agent)}
                              >
                                <Pencil className="size-3.5" aria-hidden />
                              </Button>
                            ) : null}
                            {mayArchive && !agent.archived_at ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={t('agents.archive')}
                                onClick={() => setArchiving(agent)}
                              >
                                <Archive className="size-3.5" aria-hidden />
                              </Button>
                            ) : null}
                          </div>
                        </TD>
                      ) : null}
                    </TR>
                  ))}
                </TBody>
              </Table>
            </TableWrap>
            <p className="text-xs text-muted">{t('agents.total', { count: data.total })}</p>
            {linesFailed ? (
              // Never let a failed lookup read as "this agent has no number".
              <p className="text-xs text-warn">{t('agents.linesPartial')}</p>
            ) : null}
          </>
        )}
      </QueryBoundary>

      {mayWrite ? (
        <>
          {/* Create is a FLOW, not a form: agent, number and enrolment code
              in one dialog that ends on the code. Edit stays a plain form. */}
          <CreateAgentModal open={creating} onOpenChange={setCreating} />
          <AgentModal
            open={editing !== null}
            onOpenChange={(open) => !open && setEditing(null)}
            agent={editing}
          />
        </>
      ) : null}
      {mayArchive ? (
        <ArchiveAgentModal
          open={archiving !== null}
          onOpenChange={(open) => !open && setArchiving(null)}
          agent={archiving}
        />
      ) : null}
    </Page>
  )
}
