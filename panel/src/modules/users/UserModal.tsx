/**
 * Create or edit a panel account (CONVENTIONS-CLIENT.md §3 — never an inline
 * form).
 *
 * **This creates a login, and the form says so in one Uzbek line.** The two
 * mistakes it exists to prevent are "I added Aziz but he cannot sign in" and
 * "I created a user and now there are two Azizes"; both come from treating a
 * user and an agent as one thing.
 *
 * Choosing `sales` forces an agent picker, because own-scope narrowing filters
 * on `agent_id` and a `sales` login without one would see either nothing or
 * everything — the server answers 409 `sales_user_requires_agent` rather than
 * guessing, and this form does not let it get that far.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { useAgentDirectory } from '@/modules/agents/api'
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'
import { SELECT_CLASS } from '@/shared/ui/filters'

import { MIN_PASSWORD_LENGTH, useCreateUser, useUpdateUser, type User, type UserRole } from './api'
import { ROLE_LABEL, ROLES } from './labels'

interface Draft {
  email: string
  full_name: string
  role: UserRole
  agent_id: string
  password: string
  is_active: boolean
}

const EMPTY: Draft = {
  email: '',
  full_name: '',
  role: 'manager',
  agent_id: '',
  password: '',
  is_active: true,
}

function draftFrom(user: User | null): Draft {
  if (!user) return EMPTY
  return {
    email: user.email,
    full_name: user.full_name,
    role: user.role,
    agent_id: user.agent_id ?? '',
    password: '',
    is_active: user.is_active,
  }
}

export function UserModal({
  open,
  onOpenChange,
  user,
  isSelf,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User | null
  /** Editing your own account: the server refuses a demotion or a
   *  deactivation, so the form does not offer them. */
  isSelf: boolean
}) {
  const editing = user !== null
  const [draft, setDraft] = useState<Draft>(() => draftFrom(user))
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (open) {
      setDraft(draftFrom(user))
      setTouched(false)
    }
  }, [open, user])

  const agentsQuery = useAgentDirectory(open)
  const create = useCreateUser()
  const update = useUpdateUser(user?.id ?? '')
  const mutation = editing ? update : create

  const needsAgent = draft.role === 'sales'
  const emailMissing = !editing && draft.email.trim() === ''
  const nameMissing = draft.full_name.trim() === ''
  const passwordTooShort = !editing && draft.password.length < MIN_PASSWORD_LENGTH
  const agentMissing = needsAgent && draft.agent_id === ''
  const invalid = emailMissing || nameMissing || passwordTooShort || agentMissing

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (invalid) return

    const done = { onSuccess: () => onOpenChange(false) }

    if (editing) {
      update.mutate(
        {
          full_name: draft.full_name.trim(),
          role: draft.role,
          // Only a `sales` account carries one; clearing it on any other role
          // keeps the two from drifting apart in the database.
          agent_id: needsAgent ? draft.agent_id : null,
          is_active: draft.is_active,
        },
        done,
      )
      return
    }

    create.mutate(
      {
        email: draft.email.trim(),
        full_name: draft.full_name.trim(),
        role: draft.role,
        password: draft.password,
        ...(needsAgent ? { agent_id: draft.agent_id } : {}),
      },
      done,
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? t('users.editTitle') : t('users.createTitle')}
      // The one line that keeps a login and a salesperson apart.
      description={t('users.createHint')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={invalid}
    >
      <ModalFields>
        {editing ? null : (
          <ModalField
            htmlFor="user-email"
            label={t('users.fieldEmail')}
            error={touched && emailMissing ? t('users.emailRequired') : undefined}
          >
            <Input
              id="user-email"
              type="email"
              autoComplete="off"
              value={draft.email}
              onChange={(event) => setDraft({ ...draft, email: event.target.value })}
            />
          </ModalField>
        )}

        <ModalField
          htmlFor="user-name"
          label={t('users.fieldName')}
          error={touched && nameMissing ? t('users.nameRequired') : undefined}
        >
          <Input
            id="user-name"
            value={draft.full_name}
            onChange={(event) => setDraft({ ...draft, full_name: event.target.value })}
          />
        </ModalField>

        <ModalField htmlFor="user-role" label={t('users.fieldRole')}>
          <select
            id="user-role"
            className={`${SELECT_CLASS} w-full`}
            value={draft.role}
            // Demoting yourself is refused by the server (409
            // `cannot_modify_self`), so it is not offered here either.
            disabled={isSelf}
            onChange={(event) => setDraft({ ...draft, role: event.target.value as UserRole })}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {t(ROLE_LABEL[role])}
              </option>
            ))}
          </select>
        </ModalField>

        {needsAgent ? (
          <ModalField
            htmlFor="user-agent"
            label={t('users.fieldAgent')}
            error={touched && agentMissing ? t('users.agentRequired') : undefined}
          >
            <select
              id="user-agent"
              className={`${SELECT_CLASS} w-full`}
              value={draft.agent_id}
              onChange={(event) => setDraft({ ...draft, agent_id: event.target.value })}
            >
              <option value="">{t('users.chooseAgent')}</option>
              {(agentsQuery.data?.items ?? [])
                .filter((agent) => agent.archived_at === null)
                .map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.full_name}
                  </option>
                ))}
            </select>
            <p className="mt-1 text-2xs text-muted">{t('users.agentHint')}</p>
          </ModalField>
        ) : null}

        {editing ? (
          <ModalField htmlFor="user-active" label={t('users.fieldActive')}>
            <label className="flex items-center gap-2 text-xs text-muted">
              <input
                id="user-active"
                type="checkbox"
                checked={draft.is_active}
                disabled={isSelf}
                onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })}
              />
              {isSelf ? t('users.cannotDeactivateSelf') : t('users.fieldActiveHint')}
            </label>
          </ModalField>
        ) : (
          <ModalField
            htmlFor="user-password"
            label={t('users.fieldPassword')}
            error={
              touched && passwordTooShort
                ? t('users.passwordTooShort', { n: MIN_PASSWORD_LENGTH })
                : undefined
            }
          >
            <Input
              id="user-password"
              type="password"
              autoComplete="new-password"
              value={draft.password}
              onChange={(event) => setDraft({ ...draft, password: event.target.value })}
            />
            <p className="mt-1 text-2xs text-muted">{t('users.passwordHint')}</p>
          </ModalField>
        )}

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
