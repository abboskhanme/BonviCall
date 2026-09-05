/**
 * Edit one threshold.
 *
 * The input is chosen from the row's own `value_type` rather than from the
 * key, because the server owns both and a key-based guess would be wrong the
 * first time somebody adds a setting. A `list` value is edited as JSON — it is
 * `working_hours.workdays` and `alerts.email_to`, two rows, and a bespoke
 * editor for each would be more code than the whole page.
 *
 * Retention is NOT edited here: it has its own dialog, because it is the only
 * value on the page whose change destroys something.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { Input } from '@/shared/ui/primitives'

import { settingString, useUpdateSetting, type Setting } from './api'

/** Parse the typed value back out of the field, or say it is not valid. */
function parseValue(
  raw: string,
  valueType: string,
): { ok: true; value: unknown } | { ok: false } {
  const trimmed = raw.trim()
  switch (valueType) {
    case 'int': {
      const value = Number(trimmed)
      return Number.isInteger(value) ? { ok: true, value } : { ok: false }
    }
    case 'bool':
      if (trimmed === 'true' || trimmed === 'false') return { ok: true, value: trimmed === 'true' }
      return { ok: false }
    case 'list':
      try {
        const value: unknown = JSON.parse(trimmed)
        return Array.isArray(value) ? { ok: true, value } : { ok: false }
      } catch {
        // A half-typed array is not an error worth a red banner mid-keystroke;
        // the submit button simply stays disabled.
        return { ok: false }
      }
    default:
      return { ok: true, value: trimmed }
  }
}

export function SettingModal({
  open,
  onOpenChange,
  setting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  setting: Setting | null
}) {
  const [raw, setRaw] = useState('')
  const mutation = useUpdateSetting()

  useEffect(() => {
    if (open && setting) setRaw(settingString(setting))
  }, [open, setting])

  const parsed = setting ? parseValue(raw, setting.value_type) : { ok: false as const }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!setting || !parsed.ok) return
    mutation.mutate(
      // No confirmation: this modal never edits retention, which is the only
      // key whose change deletes anything.
      { key: setting.key, value: parsed.value, confirm: false },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('settings.editTitle')}
      description={setting?.key}
      onSubmit={handleSubmit}
      submitting={mutation.status === 'pending'}
      submitDisabled={!parsed.ok}
    >
      <ModalFields>
        <ModalField
          htmlFor="setting-value"
          label={t('settings.colValue')}
          error={parsed.ok ? undefined : t('settings.valueInvalid', { type: setting?.value_type ?? '' })}
        >
          <Input
            id="setting-value"
            value={raw}
            onChange={(event) => setRaw(event.target.value)}
            autoFocus
          />
          <p className="mt-1 text-2xs text-muted">
            {t('settings.valueType', { type: setting?.value_type ?? '' })}
          </p>
        </ModalField>

        {setting?.description_uz ? (
          <p className="text-xs text-muted">{setting.description_uz}</p>
        ) : null}

        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
