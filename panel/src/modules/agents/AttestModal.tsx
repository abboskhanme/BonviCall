/**
 * Attesting that a phone really is on a number, on an admin's own authority.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This is not a confirmation dialog. "Are you sure?" asks about resolve; what
 * the admin needs to understand is **what they are asserting**: that they know
 * this handset holds this line, without the phone having proved it. The system
 * will treat that assertion as the identity anchor for every call the phone
 * ever uploads.
 *
 * The reason is required and is not ceremony — `attest_reason` is a column and
 * lands in the audit row. Six months later, "why is this installation trusted"
 * has to have an answer, and an unexplained attestation is indistinguishable
 * from a mistake.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ShieldQuestion } from 'lucide-react'

import { useAttestInstallation } from '@/modules/devices/api'
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatPhone } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

/** Enough that "test" does not pass for an explanation. */
const MIN_REASON_LENGTH = 10

export function AttestModal({
  open,
  onOpenChange,
  installationId,
  agentName,
  e164,
  reasonHintKey,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  installationId: string
  agentName: string
  e164: string | null
  /** Why the automatic routes cannot finish — shown so the admin is not
   *  reaching for this without knowing what it replaces. */
  reasonHintKey: 'attest.becauseMsisdn' | 'attest.becauseReceiver' | 'attest.becauseBoth'
}) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)
  const mutation = useAttestInstallation(installationId)

  useEffect(() => {
    if (open) {
      setReason('')
      setTouched(false)
    }
  }, [open])

  const tooShort = reason.trim().length < MIN_REASON_LENGTH

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (tooShort) return
    mutation.mutate({ reason: reason.trim() }, { onSuccess: () => onOpenChange(false) })
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('attest.title')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={tooShort}
      submitLabel={t('attest.action')}
    >
      <ModalFields>
        {/* What is being asserted, before the button — not after it. */}
        <div className="flex items-start gap-3 rounded-md border border-warn/40 bg-warn/5 p-3">
          <ShieldQuestion className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <div className="space-y-1">
            <p className="text-sm font-medium text-text">
              {t('attest.asserting', {
                name: agentName,
                number: e164 ? (formatPhone(e164) ?? e164) : '',
              })}
            </p>
            <p className="text-xs text-muted">{t('attest.explain')}</p>
          </div>
        </div>

        {/* Why the automatic routes are unavailable, so this never reads as a
            shortcut somebody took because it was quicker. */}
        <p className="text-xs text-muted">{t(reasonHintKey)}</p>

        <ModalField
          htmlFor="attest-reason"
          label={t('attest.reason')}
          error={touched && tooShort ? t('attest.reasonRequired', { n: MIN_REASON_LENGTH }) : undefined}
        >
          <Input
            id="attest-reason"
            value={reason}
            placeholder={t('attest.reasonHint')}
            onChange={(event) => setReason(event.target.value)}
          />
          {/* It goes in the audit row, and that is the point of it. */}
          <p className="mt-1 text-2xs text-muted">{t('attest.reasonAudited')}</p>
        </ModalField>

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
