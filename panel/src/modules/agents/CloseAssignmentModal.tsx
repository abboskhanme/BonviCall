/**
 * End a holding period.
 *
 * Closing an assignment is not "unlink a number" — it is a statement about
 * **when** this person stopped holding the line, and the server re-attributes
 * calls from that instant. A call made the day before the close date stays
 * with this agent; one made the day after does not (SPEC §3.3, D-08).
 *
 * The date therefore defaults to today and is editable, because the common
 * real case is an admin recording a handover that happened last Friday. A
 * modal that silently used "now" would file four days of somebody else's calls
 * under the wrong name, and nothing on any screen would ever say so.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatDate, formatPhone } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { useCloseAssignment, type AgentAssignment } from '@/modules/numbers/api'

/** `yyyy-mm-dd` for a date input, in Asia/Tashkent rather than UTC. */
function todayInput(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tashkent',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
  return parts
}

export function CloseAssignmentModal({
  open,
  onOpenChange,
  row,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  row: AgentAssignment | null
}) {
  const [validTo, setValidTo] = useState(todayInput())
  const mutation = useCloseAssignment(row?.assignment.id ?? '')

  useEffect(() => {
    if (open) setValidTo(todayInput())
  }, [open])

  // The period is [valid_from, valid_to) and the server requires the end to be
  // after the start; offering an earlier date would only produce a 422.
  const minDate = row ? row.assignment.valid_from.slice(0, 10) : undefined
  const invalid = minDate !== undefined && validTo < minDate

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!row || invalid) return
    mutation.mutate(
      // Midnight Tashkent, so the boundary lands on the calendar day the admin
      // picked rather than five hours into the previous one.
      { valid_to: `${validTo}T00:00:00+05:00` },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('numbers.closeTitle')}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={row === null || invalid}
      submitLabel={t('numbers.closeAction')}
    >
      <ModalFields>
        <p className="text-sm text-text">
          {t('numbers.closeConfirm', {
            number: row ? (formatPhone(row.number.e164) ?? row.number.e164) : '',
            from: row ? formatDate(row.assignment.valid_from) : '',
          })}
        </p>

        <ModalField
          htmlFor="close-valid-to"
          label={t('numbers.fieldValidTo')}
          error={invalid ? t('numbers.validToTooEarly') : undefined}
        >
          <Input
            id="close-valid-to"
            type="date"
            value={validTo}
            min={minDate}
            onChange={(event) => setValidTo(event.target.value)}
          />
        </ModalField>

        {/* Said plainly, because it is the consequence people do not expect. */}
        <p className="text-xs text-muted">{t('numbers.closeExplain')}</p>

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
