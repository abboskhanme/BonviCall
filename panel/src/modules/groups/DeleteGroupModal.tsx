/**
 * Confirming a group deletion.
 *
 * The sentence names what goes with it. Surveys and their ratings cascade —
 * correctly, because the rating was of a conversation in THIS chat and there
 * is nothing left to attribute it to — and an admin has to be told that before
 * they press the button, not afterwards.
 */
import { useState } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal } from '@/shared/ui/Modal'

import { useDeleteGroup, type Group } from './api'

export function DeleteGroupModal({
  group,
  onClose,
}: {
  group: Group | null
  onClose: () => void
}) {
  const remove = useDeleteGroup()
  const [error, setError] = useState<string | null>(null)

  return (
    <Modal
      open={group !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t('groups.deleteTitle')}
      description={group?.title}
      danger
      submitLabel={t('groups.deleteAction')}
      submitting={remove.status === 'pending'}
      onSubmit={(event) => {
        event.preventDefault()
        if (!group) return
        setError(null)
        remove.mutate(group.id, {
          onSuccess: onClose,
          onError: (failure) => setError(messageForError(failure)),
        })
      }}
    >
      <p className="text-sm leading-relaxed text-text">
        {t('groups.deleteConfirm', { title: group?.title ?? '' })}
      </p>
      <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
        {t('groups.deleteOnlyLeft')}
      </p>
      {error ? (
        <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad">{error}</p>
      ) : null}
    </Modal>
  )
}
