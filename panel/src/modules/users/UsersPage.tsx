/**
 * `/users` — panel accounts. **Not agents.**
 *
 * A user is a login; an agent is a salesperson; creating one never creates the
 * other (SPEC §3.2). Most salespeople have no account at all — they need a
 * phone, not a password — and this page deliberately grows no number or
 * enrolment controls, because those belong to the person, and the person lives
 * on `/agents/:id`.
 *
 * Two server refusals are surfaced as sentences rather than as generic
 * failures, and both are refusals to do something that looks reasonable:
 *   • the last active admin cannot be demoted or deactivated — a panel with no
 *     admin can only be repaired from a shell;
 *   • you cannot deactivate or demote yourself.
 * The buttons are disabled with an explanation, and the server still decides.
 */
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { KeyRound, Pencil, Plus, ShieldAlert } from 'lucide-react'

import { agentNameLookup, useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { EM_DASH, formatInstantTitle } from '@/shared/lib/format'
import { relativeText } from '@/shared/lib/relativeText'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { EnumFilter } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { ResetPasswordModal } from './ResetPasswordModal'
import { UserModal } from './UserModal'
import { isLastActiveAdmin, useUsers, type User, type UserRole } from './api'
import { ROLE_LABEL, ROLE_TONE } from './labels'

const PARAM_ROLE = 'role'

function parseRole(raw: string | null): UserRole | undefined {
  return raw !== null && raw in ROLE_LABEL ? (raw as UserRole) : undefined
}

export function UsersPage() {
  const can = useAuth((state) => state.can)
  const currentUser = useAuth((state) => state.user)
  const mayWrite = can(Perm.USERS_WRITE)

  const [searchParams, setSearchParams] = useSearchParams()
  const role = parseRole(searchParams.get(PARAM_ROLE))

  const [editing, setEditing] = useState<User | null>(null)
  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<User | null>(null)

  const usersQuery = useUsers(role ? { role } : {})
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const agentName = agentNameLookup(agentsQuery.data?.items)

  function applyFilter(value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(PARAM_ROLE)
    else next.set(PARAM_ROLE, value)
    setSearchParams(next, { replace: true })
  }

  return (
    <Page>
      <PageHeader
        title={t('page.users')}
        description={t('users.subtitle')}
        actions={
          mayWrite ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden />
              {t('users.create')}
            </Button>
          ) : undefined
        }
      />

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <EnumFilter
          label={t('users.filterRole')}
          allLabel={t('calls.filterAny')}
          labels={ROLE_LABEL}
          value={role}
          onChange={applyFilter}
        />
      </Card>

      <QueryBoundary
        query={usersQuery}
        isEmpty={(data) => data.items.length === 0}
        emptyTitle={role ? t('users.emptyFiltered') : t('users.emptyAll')}
        emptyHint={role ? t('users.emptyFilteredHint') : t('users.emptyAllHint')}
        skeletonRows={5}
      >
        {(data) => (
          <TableWrap>
            <Table>
              <THead>
                <tr>
                  <TH>{t('users.colName')}</TH>
                  <TH>{t('users.colEmail')}</TH>
                  <TH>{t('users.colRole')}</TH>
                  <TH>{t('users.colAgent')}</TH>
                  <TH>{t('users.colStatus')}</TH>
                  <TH>{t('users.colLastLogin')}</TH>
                  {mayWrite ? <TH className="w-0" /> : null}
                </tr>
              </THead>
              <TBody>
                {data.items.map((user) => {
                  const isSelf = user.id === currentUser?.id
                  const lastAdmin = isLastActiveAdmin(data.items, user)
                  // Locked for a reason the row can name; the server refuses
                  // it too, which is the check that decides anything.
                  const locked = isSelf || lastAdmin
                  return (
                    <TR key={user.id}>
                      <TD className="font-medium text-text">
                        {user.full_name}
                        {isSelf ? (
                          <span className="ms-2 text-2xs text-muted">{t('users.you')}</span>
                        ) : null}
                      </TD>
                      <TD className="font-mono text-xs text-muted">{user.email}</TD>
                      <TD>
                        <Badge tone={ROLE_TONE[user.role]}>{t(ROLE_LABEL[user.role])}</Badge>
                      </TD>
                      <TD className="whitespace-nowrap">
                        {/* Only a `sales` account names an agent, and the link
                            goes to the salesperson, not to another login. */}
                        {user.agent_id ? (
                          <Link
                            to={`/agents/${user.agent_id}`}
                            className="text-text underline-offset-2 hover:text-accent hover:underline"
                          >
                            {agentName(user.agent_id) ?? t('users.unknownAgent')}
                          </Link>
                        ) : (
                          EM_DASH
                        )}
                      </TD>
                      <TD>
                        <div className="flex flex-wrap items-center gap-1">
                          {user.is_active ? (
                            <Badge tone="good">{t('users.statusActive')}</Badge>
                          ) : (
                            <Badge tone="neutral">{t('users.statusInactive')}</Badge>
                          )}
                          {user.must_change_password ? (
                            <Badge tone="warn">{t('users.mustChange')}</Badge>
                          ) : null}
                        </div>
                      </TD>
                      <TD
                        className="whitespace-nowrap text-muted"
                        title={
                          user.last_login_at ? formatInstantTitle(user.last_login_at) : undefined
                        }
                      >
                        {user.last_login_at ? relativeText(user.last_login_at) : t('users.neverIn')}
                      </TD>
                      {mayWrite ? (
                        <TD>
                          <div className="flex items-center justify-end gap-1">
                            {lastAdmin ? (
                              <span
                                className="text-2xs text-warn"
                                title={t('errors.last_admin')}
                              >
                                <ShieldAlert className="size-3.5" aria-hidden />
                              </span>
                            ) : null}
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('users.edit')}
                              onClick={() => setEditing(user)}
                            >
                              <Pencil className="size-3.5" aria-hidden />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('users.reset')}
                              // Resetting your own password here would sign you
                              // out mid-session; `/auth/password` is the route
                              // for that and it asks for the current one.
                              disabled={isSelf}
                              onClick={() => setResetting(user)}
                            >
                              <KeyRound className="size-3.5" aria-hidden />
                            </Button>
                          </div>
                          {/* Both reasons, when both apply: an admin editing
                              their own account while being the last one is
                              blocked twice over, and naming only the first
                              would make the second look like a bug when it
                              still refuses after they add a colleague. */}
                          {locked ? (
                            <p className="text-end text-2xs text-muted">
                              {[
                                isSelf ? t('users.selfLocked') : null,
                                lastAdmin ? t('users.lastAdminLocked') : null,
                              ]
                                .filter(Boolean)
                                .join(' · ')}
                            </p>
                          ) : null}
                        </TD>
                      ) : null}
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </QueryBoundary>

      {mayWrite ? (
        <>
          <UserModal open={creating} onOpenChange={setCreating} user={null} isSelf={false} />
          <UserModal
            open={editing !== null}
            onOpenChange={(open) => !open && setEditing(null)}
            user={editing}
            isSelf={editing?.id === currentUser?.id}
          />
          <ResetPasswordModal
            open={resetting !== null}
            onOpenChange={(open) => !open && setResetting(null)}
            user={resetting}
          />
        </>
      ) : null}
    </Page>
  )
}
