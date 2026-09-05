/**
 * Changing your own password.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * `seed.py` and every admin-issued reset set `must_change_password`, so
 * without this dialog the flag was permanent and the panel had no way to
 * clear it — the endpoint existed and nothing reached it.
 *
 * Two things this says out loud, because neither is guessable:
 *
 *   it asks for the CURRENT password, which is what makes it self-service —
 *   an admin does not have it and uses the reset on `/users` instead;
 *
 *   success **ends every other session** this account holds. That is a
 *   security property worth advertising rather than hiding: it is the reason
 *   changing your password is the right response to "I think somebody saw it".
 *
 * When `must_change_password` is set the dialog cannot be dismissed. That is
 * deliberate and narrow: it is the one state where letting somebody past would
 * leave an account with a password an admin chose and typed into a chat.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { changePassword } from './api'
import { useAuth } from './store'

/** SPEC §4.7: minimum ten characters and no other composition rule. */
export const MIN_PASSWORD_LENGTH = 10

export function ChangePasswordModal({
  open,
  onOpenChange,
  forced,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Set when `must_change_password` is true: the dialog cannot be closed. */
  forced: boolean
}) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [touched, setTouched] = useState(false)
  const passwordChanged = useAuth((state) => state.passwordChanged)

  const mutation = useMutation({
    mutationFn: changePassword,
    onSuccess: () => {
      passwordChanged()
      onOpenChange(false)
    },
  })

  useEffect(() => {
    if (open) {
      setCurrent('')
      setNext('')
      setRepeat('')
      setTouched(false)
    }
  }, [open])

  const tooShort = next.length < MIN_PASSWORD_LENGTH
  const mismatch = repeat !== '' && repeat !== next
  const invalid = current === '' || tooShort || next !== repeat

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (invalid) return
    mutation.mutate({ current_password: current, new_password: next })
  }

  return (
    <Modal
      open={open}
      // A forced change is the one place the panel refuses to be dismissed.
      onOpenChange={(value) => {
        if (forced && !value) return
        onOpenChange(value)
      }}
      title={t('password.title')}
      description={forced ? t('password.forcedHint') : t('password.hint')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={invalid}
      submitLabel={t('password.action')}
    >
      <ModalFields>
        <ModalField
          htmlFor="current-password"
          label={t('password.current')}
          error={touched && current === '' ? t('password.currentRequired') : undefined}
        >
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </ModalField>

        <ModalField
          htmlFor="new-password"
          label={t('password.next')}
          error={
            touched && tooShort ? t('users.passwordTooShort', { n: MIN_PASSWORD_LENGTH }) : undefined
          }
        >
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          <p className="mt-1 text-2xs text-muted">{t('users.passwordHint')}</p>
        </ModalField>

        <ModalField
          htmlFor="repeat-password"
          label={t('password.repeat')}
          error={mismatch ? t('password.mismatch') : undefined}
        >
          <Input
            id="repeat-password"
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(event) => setRepeat(event.target.value)}
          />
        </ModalField>

        {/* Advertised, not hidden: it is the reason this is the right response
            to "somebody may have seen my password". */}
        <p className="text-xs text-muted">{t('password.revokesSessions')}</p>

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
