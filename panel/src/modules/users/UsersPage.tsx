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
import { useSearchParams } from 'react-router-dom'
import { KeyRound, Pencil, Plus, ShieldAlert } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { formatInstantTitle } from '@/shared/lib/format'
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
                  <TH>{t('users.colRole')}</TH>
                  <TH>{t('users.colStatus')}</TH>
                  <TH>{t('users.colLastLogin')}</TH>
                  {mayWrite ? <TH className="w-0" /> : null}
                </tr>
              </THead>
              <TBody>
                {data.items.map((user) => {
                  const isSelf = user.id === currentUser?.id
                  const lastAdmin = isLastActiveAdmin(data.items, user)
                  // Both guards can apply at once — an admin editing their own
                  // account while being the last one is blocked twice over —
                  // so both reasons travel, joined, in one `title`. The server
                  // refuses either way; this only explains the refusal.
                  const editReason =
                    [
                      isSelf ? t('users.selfLocked') : null,
                      lastAdmin ? t('users.lastAdminLocked') : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || null
                  return (
                    <TR key={user.id}>
                      <TD className="whitespace-nowrap font-medium text-text">
                        {user.full_name}
                        {isSelf ? (
                          <span className="ms-2 text-2xs text-muted">{t('users.you')}</span>
                        ) : null}
                        {lastAdmin ? (
                          /* Was a bare icon on its own line above the buttons.
                             Inline and captioned, it costs no height. */
                          <span
                            className="ms-2 inline-flex items-center gap-1 text-2xs text-warn"
                            title={t('errors.last_admin')}
                          >
                            <ShieldAlert className="size-3" aria-hidden />
                            {t('users.lastAdminShort')}
                          </span>
                        ) : null}
                        {user.must_change_password ? (
                          <span className="ms-2 text-2xs text-warn">{t('users.mustChange')}</span>
                        ) : null}
                      </TD>
                      <TD>
                        <Badge tone={ROLE_TONE[user.role]}>{t(ROLE_LABEL[user.role])}</Badge>
                      </TD>
                      <TD className="whitespace-nowrap">
                        {/* One badge. `must_change_password` is a pending
                            action, not a second status, and showing them as
                            two equal badges read as two states. It moves
                            beside the name as a quiet note. */}
                        {user.is_active ? (
                          <Badge tone="good">{t('users.statusActive')}</Badge>
                        ) : (
                          <Badge tone="neutral">{t('users.statusInactive')}</Badge>
                        )}
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
                          {/* ═══════════════════════════════════════════════
                              One line, always.

                              The reasons used to sit under the buttons as a
                              caption, which wrapped across four lines in a
                              narrow column and made this row three times the
                              height of its neighbours — the table stopped
                              looking like a table.

                              They are not dropped, though: a disabled button
                              with no explanation is its own small cruelty.
                              Somebody clicks, nothing happens, and they never
                              find out why. The reason moves onto the control
                              as a `title`, where it is available on hover and
                              read out by a screen reader, and the row stays
                              one line high.
                              ═══════════════════════════════════════════════ */}
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('users.edit')}
                              title={editReason ?? t('users.edit')}
                              onClick={() => setEditing(user)}
                            >
                              <Pencil className="size-3.5" aria-hidden />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('users.reset')}
                              // Resetting your own password here would sign
                              // you out mid-session; `/auth/password` is the
                              // route for that and it asks for the current one.
                              title={isSelf ? t('users.selfLocked') : t('users.reset')}
                              disabled={isSelf}
                              onClick={() => setResetting(user)}
                            >
                              <KeyRound className="size-3.5" aria-hidden />
                            </Button>
                          </div>
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
