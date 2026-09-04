/**
 * Revoke an installation (UC-08).
 *
 * The response reports what the phone was **still holding at last contact** —
 * queued records and bytes that have not reached the server. Revoking cuts the
 * token, so anything still in that queue is lost, and the admin has to be told
 * the number *before* they decide, not after.
 *
 * That is why the count is shown after the call rather than hidden behind a
 * generic success toast: "revoked, 41 records were still queued" is the
 * sentence somebody needs in order to go and ask for the phone back.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatBytes } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { useRevokeInstallation, type RevokeResponse } from './api'

export function RevokeDeviceModal({
  open,
  onOpenChange,
  installationId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  installationId: string
}) {
  const [reason, setReason] = useState('')
  const [result, setResult] = useState<RevokeResponse | null>(null)
  const mutation = useRevokeInstallation(installationId)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    mutation.mutate(
      { reason: reason.trim() === '' ? null : reason.trim() },
      { onSuccess: (response) => setResult(response) },
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={(value) => {
        onOpenChange(value)
        if (!value) {
          setResult(null)
          setReason('')
        }
      }}
      title={t('devices.revokeTitle')}
      onSubmit={result ? undefined : handleSubmit}
      submitLabel={t('devices.revokeAction')}
      submitting={mutation.status === 'pending'}
      danger
    >
      <ModalFields>
        {result ? (
          <div className="space-y-2">
            <p className="text-sm text-text">{t('devices.revokeDone')}</p>
            {/* The number that decides whether anyone needs to chase the
                handset. Shown plainly, not as a toast that disappears. */}
            <p className="text-sm text-warn">
              {t('devices.revokePending', {
                records: result.pending_records ?? 0,
                bytes: formatBytes(result.pending_bytes ?? 0),
              })}
            </p>
          </div>
        ) : (
          <>
            <p className="text-sm text-text">{t('devices.revokeConfirm')}</p>
            <p className="text-xs text-muted">{t('devices.revokeExplain')}</p>
            <ModalField htmlFor="revoke-reason" label={t('devices.revokeReason')}>
              <Input
                id="revoke-reason"
                value={reason}
                placeholder={t('devices.revokeReasonHint')}
                onChange={(event) => setReason(event.target.value)}
              />
            </ModalField>
          </>
        )}

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
