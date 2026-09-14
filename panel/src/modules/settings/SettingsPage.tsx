/**
 * `/settings` — your own account, and everybody else's password.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The profile menu used to offer "Parolni o'zgartirish" and nothing else, so
 * the one thing an account owner can do about their own account was a modal
 * with no home. This is that home: your own password here, and — for an admin
 * — every other account's, because the person who has to reset a forgotten
 * password is the person the menu belongs to, not somebody hunting for a key
 * icon on a list page.
 *
 * **Nothing new is trusted.** Both actions are the existing modals against the
 * existing endpoints: `POST /auth/password` proves the current password before
 * it changes anything, and `POST /users/{id}/password` is `users:write` and
 * audited. The page is an entrance, not a second implementation.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { KeyRound } from 'lucide-react'

import { ChangePasswordModal } from '@/modules/auth/ChangePasswordModal'
import { useAuth } from '@/modules/auth/store'
import { ResetPasswordModal } from '@/modules/users/ResetPasswordModal'
import { useUsers, type User } from '@/modules/users/api'
import { ROLE_LABEL, ROLE_TONE } from '@/modules/users/labels'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { Field, FieldGrid, Section } from '@/shared/ui/detail'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

function OtherPasswords({ onReset }: { onReset: (user: User) => void }) {
  const currentUser = useAuth((state) => state.user)
  const query = useUsers({})

  return (
    <Section
      title={t('settings.othersTitle')}
      description={t('settings.othersSubtitle')}
    >
      <QueryBoundary query={query} isEmpty={(data) => data.items.length === 0} skeletonRows={3}>
        {(data) => (
          <TableWrap>
            <Table>
              <THead>
                <tr>
                  <TH>{t('users.colName')}</TH>
                  <TH>{t('users.colRole')}</TH>
                  <TH className="w-0" />
                </tr>
              </THead>
              <TBody>
                {data.items.map((user) => (
                  <TR key={user.id}>
                    <TD className="whitespace-nowrap font-medium text-text">
                      {user.full_name}
                      {user.must_change_password ? (
                        <span className="ms-2 text-2xs text-warn">{t('users.mustChange')}</span>
                      ) : null}
                    </TD>
                    <TD className="whitespace-nowrap">
                      <Badge tone={ROLE_TONE[user.role]}>{t(ROLE_LABEL[user.role])}</Badge>
                    </TD>
                    <TD>
                      <div className="flex justify-end">
                        {/* Your own password is changed above, with the
                            current one as proof. Resetting it from here would
                            be a way to skip that, so the row that is you
                            offers nothing. */}
                        {user.id === currentUser?.id ? null : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => onReset(user)}
                            aria-label={t('settings.resetFor', { name: user.full_name })}
                          >
                            <KeyRound className="size-3.5" aria-hidden />
                            <span>{t('settings.reset')}</span>
                          </Button>
                        )}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </QueryBoundary>
    </Section>
  )
}

export function SettingsPage() {
  const user = useAuth((state) => state.user)
  const can = useAuth((state) => state.can)
  const [changing, setChanging] = useState(false)
  const [resetting, setResetting] = useState<User | null>(null)

  return (
    <Page>
      <PageHeader title={t('page.settings')} description={t('settings.subtitle')} />

      <Section title={t('settings.mineTitle')} description={t('settings.mineSubtitle')}>
        <Card className="p-4">
          <FieldGrid>
            <Field label={t('settings.name')} value={user?.full_name} />
            {/* The login, named for what it is. It stopped being an e-mail on
                2026-09-13 and stopped being shown as one everywhere else. */}
            <Field label={t('auth.email')} value={user?.email} mono />
            <Field label={t('users.colRole')}>
              {user ? (
                <Badge tone={ROLE_TONE[user.role]}>{t(ROLE_LABEL[user.role])}</Badge>
              ) : null}
            </Field>
          </FieldGrid>
          <div className="mt-4">
            <Button variant="secondary" size="sm" onClick={() => setChanging(true)}>
              <KeyRound className="size-4" aria-hidden />
              {t('password.title')}
            </Button>
          </div>
        </Card>
      </Section>

      {can(Perm.USERS_WRITE) ? <OtherPasswords onReset={setResetting} /> : null}

      {/* `forced` is the boot-time dialog an account with
          `must_change_password` cannot dismiss. Here the reader chose to
          open it, so they may close it. */}
      <ChangePasswordModal open={changing} onOpenChange={setChanging} forced={false} />
      <ResetPasswordModal
        open={resetting !== null}
        onOpenChange={(open) => setResetting(open ? resetting : null)}
        user={resetting}
      />
    </Page>
  )
}
