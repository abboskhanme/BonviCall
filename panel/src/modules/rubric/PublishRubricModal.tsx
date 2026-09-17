/**
 * "Save" on the rubric page opens this, and the wording is the point:
 * **publishing a new version**, not saving an edit.
 *
 * The version that produced yesterday's scores is never modified — every score
 * names it in `rubric_version` — so the dialog asks for a name and a note. The
 * note is the only place the reason for a change survives, and six months later
 * "why did the average drop in October?" is answered by reading it.
 *
 * The server's refusal is rendered HERE rather than on the page behind it,
 * because this is where the decision was made: the blocks not totalling 100
 * comes back as a machine `reason` with its numbers, and `messageOfInvalid`
 * turns it into the Uzbek sentence from `uz.json`.
 */
import { useState } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Input } from '@/shared/ui/primitives'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'

import type { PublishRubricRequest } from './api'
import { messageOfInvalid } from './state'

export function PublishRubricModal({
  nextVersion,
  pending,
  error,
  onPublish,
  onClose,
}: {
  nextVersion: number
  pending: boolean
  error: unknown
  onPublish: (fields: Pick<PublishRubricRequest, 'name' | 'description'>) => void
  onClose: () => void
}) {
  const [name, setName] = useState(() => t('rubric.versionNameDefault', { version: nextVersion }))
  const [note, setNote] = useState('')

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title={t('rubric.publishTitle')}
      description={t('rubric.publishHint')}
      submitLabel={t('rubric.publish')}
      submitting={pending}
      submitDisabled={name.trim().length < 2}
      onSubmit={(event) => {
        event.preventDefault()
        onPublish({ name: name.trim(), description: note.trim() || null })
      }}
    >
      <ModalFields>
        <ModalField htmlFor="rubric-version-name" label={t('rubric.versionName')}>
          <Input
            id="rubric-version-name"
            autoFocus
            maxLength={128}
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={pending}
          />
        </ModalField>

        <ModalField htmlFor="rubric-version-note" label={t('rubric.versionNote')}>
          <textarea
            id="rubric-version-note"
            rows={3}
            maxLength={1000}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted"
            placeholder={t('rubric.versionNotePlaceholder')}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            disabled={pending}
          />
        </ModalField>

        {error ? (
          <p className="text-2xs text-bad" role="alert">
            {messageOfInvalid(error) ?? messageForError(error)}
          </p>
        ) : null}
      </ModalFields>
    </Modal>
  )
}
