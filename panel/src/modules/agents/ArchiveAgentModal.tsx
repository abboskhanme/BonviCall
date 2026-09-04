/**
 * Archive an agent — never delete one.
 *
 * The wording matters here. An archived agent keeps every call, assignment and
 * installation they ever had; hiding them from a roster is not the same as
 * removing them, and a confirmation dialog that implies deletion gets clicked
 * through by someone who then discovers the history is intact and stops
 * trusting the next dialog.
 *
 * The server refuses with 409 `agent_has_open_assignment` while the agent still
 * holds a line, because closing that assignment decides who owns the calls from
 * now on and is not a side effect anyone should get by accident. That code is
 * surfaced as its own Uzbek sentence from the catalogue rather than as a
 * generic failure — the admin needs to know what to do next, which is to hand
 * the number over first.
 */
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal } from '@/shared/ui/Modal'

import { useArchiveAgent, type Agent } from './api'

export function ArchiveAgentModal({
  open,
  onOpenChange,
  agent,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent: Agent | null
}) {
  const mutation = useArchiveAgent(agent?.id ?? '')

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={t('agents.archiveTitle')}
      onSubmit={(event) => {
        event.preventDefault()
        if (!agent) return
        mutation.mutate(undefined, { onSuccess: () => onOpenChange(false) })
      }}
      submitLabel={t('agents.archiveAction')}
      submitting={mutation.status === 'pending'}
      submitDisabled={agent === null}
      danger
    >
      <div className="space-y-3">
        <p className="text-sm text-text">
          {t('agents.archiveConfirm', { name: agent?.full_name ?? '' })}
        </p>
        <p className="text-xs text-muted">{t('agents.archiveExplain')}</p>
        {mutation.error ? (
          <p className="text-2xs text-bad">{messageForError(mutation.error)}</p>
        ) : null}
      </div>
    </Modal>
  )
}
