/**
 * Changing how long recordings are kept.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Lowering this deletes recordings, irreversibly, on a schedule.** A dialog
 * that asks "are you sure?" is asking about the wrong thing: the person
 * already knows they typed a smaller number. What they do not know is how many
 * recordings that number destroys.
 *
 * So the count is fetched before they can confirm, and it comes from the
 * SERVER — `GET /calls?has_audio=true&date_to=<cutoff>&with_total=true`, the
 * same filter builder the call list and the export use (UC-22). Counting in
 * the panel would be a second definition of "old", and the two would drift
 * exactly when somebody needed to trust this number.
 *
 * The link is deliberate too: the count is not a claim to be taken on faith,
 * it is a list somebody can open and look at before deciding.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { TriangleAlert } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import {
  RETENTION_MONTHS_KEY,
  cutoffDate,
  useRecordingsOutsideWindow,
  useUpdateSetting,
} from './api'

export function RetentionModal({
  open,
  onOpenChange,
  currentMonths,
  confirmBelowMonths,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentMonths: number
  /** Below this the server demands `confirm: true` (SPEC §3.8). */
  confirmBelowMonths: number
}) {
  const [months, setMonths] = useState(String(currentMonths))
  const mutation = useUpdateSetting()

  useEffect(() => {
    if (open) setMonths(String(currentMonths))
  }, [open, currentMonths])

  const parsed = Number(months)
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 120
  const lowering = valid && parsed < currentMonths
  const needsConfirm = valid && parsed < confirmBelowMonths

  // Only ask the server for a count when it would mean something: raising the
  // window deletes nothing.
  const preview = useRecordingsOutsideWindow(valid && lowering ? parsed : null, open)
  const affected = preview.data ?? null

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid) return
    mutation.mutate(
      {
        key: RETENTION_MONTHS_KEY,
        value: parsed,
        // The server refuses without this below the threshold, and it is sent
        // as the admin's answer to the count shown above — not as a
        // formality, which is why it is `needsConfirm` and not a constant
        // `true`: above the threshold nothing was confirmed and nothing
        // should claim to have been.
        confirm: needsConfirm,
      },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('settings.retentionTitle')}
      description={t('settings.retentionSubtitle')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={!valid}
      submitLabel={lowering ? t('settings.retentionConfirmAction') : t('common.save')}
      danger={lowering}
    >
      <ModalFields>
        <ModalField
          htmlFor="retention-months"
          label={t('settings.retentionMonths')}
          error={valid ? undefined : t('settings.retentionInvalid')}
        >
          <Input
            id="retention-months"
            type="number"
            min={1}
            max={120}
            value={months}
            onChange={(event) => setMonths(event.target.value)}
          />
          <p className="mt-1 text-2xs text-muted">
            {t('settings.retentionCurrent', { n: currentMonths })}
          </p>
        </ModalField>

        {lowering ? (
          <div className="space-y-2 rounded-md border border-bad/40 bg-bad/5 p-3">
            <p className="flex items-center gap-2 text-sm font-medium text-text">
              <TriangleAlert className="size-4 shrink-0 text-bad" aria-hidden />
              {t('settings.retentionWarning')}
            </p>

            {/* The concrete consequence, counted by the server. */}
            {preview.status === 'success' ? (
              affected === 0 ? (
                <p className="text-sm text-text">{t('settings.retentionNoneAffected')}</p>
              ) : (
                <>
                  <p className="text-sm text-text">
                    {t('settings.retentionAffected', {
                      n: formatCount(affected ?? 0),
                      date: cutoffDate(parsed),
                    })}
                  </p>
                  {/* Not a claim to be taken on faith: a list to look at. */}
                  <Link
                    to={`/calls?has_audio=true&date_to=${cutoffDate(parsed)}`}
                    className="text-xs text-accent underline-offset-2 hover:underline"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t('settings.retentionSeeList')}
                  </Link>
                </>
              )
            ) : preview.status === 'error' ? (
              // Never imply "nothing will be deleted" when we simply could not
              // count. Silence here would be the most expensive kind of
              // reassurance.
              <p className="text-sm text-warn">{t('settings.retentionCountFailed')}</p>
            ) : (
              <p className="text-sm text-muted">{t('settings.retentionCounting')}</p>
            )}

            <p className="text-xs text-muted">{t('settings.retentionIrreversible')}</p>
          </div>
        ) : null}

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
