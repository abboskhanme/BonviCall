/**
 * An admin setting somebody else's password.
 *
 * The dialog says what actually happens, because it is more than it looks:
 * the server marks the account `must_change_password` and **revokes every
 * refresh token that user holds**. So this is not a way to look at their
 * session — it ends it, and they are signed out wherever they were.
 *
 * The password is shown once, in the field, and never echoed anywhere else:
 * it is not written to the audit detail, not logged, and not returned.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { MIN_PASSWORD_LENGTH, useSetPassword, type User } from './api'

export function ResetPasswordModal({
  open,
  onOpenChange,
  user,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User | null
}) {
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)
  const mutation = useSetPassword(user?.id ?? '')

  useEffect(() => {
    if (open) {
      setPassword('')
      setTouched(false)
    }
  }, [open])

  const tooShort = password.length < MIN_PASSWORD_LENGTH

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (tooShort || !user) return
    mutation.mutate({ password }, { onSuccess: () => onOpenChange(false) })
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('users.resetTitle')}
      description={user ? t('users.resetFor', { name: user.full_name }) : undefined}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={tooShort || user === null}
      submitLabel={t('users.resetAction')}
      danger
    >
      <ModalFields>
        <ModalField
          htmlFor="reset-password"
          label={t('users.fieldPassword')}
          error={touched && tooShort ? t('users.passwordTooShort', { n: MIN_PASSWORD_LENGTH }) : undefined}
        >
          <Input
            id="reset-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </ModalField>

        {/* Said plainly, because being signed out everywhere is the part
            nobody expects from "reset the password". */}
        <p className="text-xs text-muted">{t('users.resetExplain')}</p>

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
