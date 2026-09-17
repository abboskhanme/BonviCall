/**
 * Bind, release or park one group. Editing happens only in a modal
 * (CONVENTIONS-CLIENT.md §3).
 *
 * ⚠️ Saving a binding here marks the row `manual`, and the modal says so
 * before it is saved rather than after. Automatic binding then never touches
 * that row again, which is the behaviour an admin wants and also the one that
 * surprises them if nobody mentions it.
 */
import { useEffect, useState } from 'react'

import { useAgentDirectory } from '@/modules/agents/api'
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { Modal } from '@/shared/ui/Modal'

import { useSaveGroup, type Group } from './api'

export function GroupModal({ group, onClose }: { group: Group | null; onClose: () => void }) {
  const save = useSaveGroup()
  const agents = useAgentDirectory(group !== null)
  const [agentId, setAgentId] = useState('')
  const [active, setActive] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // The form follows whichever row was opened. Without this the second group
  // opened shows the first one's employee.
  useEffect(() => {
    if (!group) return
    setAgentId(group.agent_id ?? '')
    setActive(group.is_active)
    setError(null)
  }, [group])

  const binding = agentId !== (group?.agent_id ?? '')

  return (
    <Modal
      open={group !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t('groups.bindTitle')}
      description={group?.title}
      submitLabel={t('common.save')}
      submitting={save.status === 'pending'}
      onSubmit={(event) => {
        event.preventDefault()
        if (!group) return
        setError(null)
        save.mutate(
          { id: group.id, agent_id: agentId || null, is_active: active },
          {
            onSuccess: onClose,
            onError: (failure) => setError(messageForError(failure)),
          },
        )
      }}
    >
      <div>
        <span className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('groups.chatId')}
        </span>
        <p className="mt-0.5 text-sm tabular-nums text-text">{group?.chat_id}</p>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-muted">{t('groups.agentField')}</span>
        <select
          className="h-10 rounded-md border border-border bg-surface px-2 text-sm text-text"
          value={agentId}
          onChange={(event) => setAgentId(event.target.value)}
        >
          <option value="">{t('groups.agentNone')}</option>
          {(agents.data?.items ?? []).map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.full_name}
            </option>
          ))}
        </select>
        <span className="text-2xs text-muted">{t('groups.bindHint')}</span>
      </label>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={active}
          onChange={(event) => setActive(event.target.checked)}
          className="size-4 accent-[hsl(var(--accent))]"
        />
        <span className="text-sm text-text">{t('groups.activeLabel')}</span>
      </label>
      <p className="text-2xs text-muted">{t('groups.activeHint')}</p>

      {binding && agentId ? (
        <p className="rounded-md bg-warn/10 px-3 py-2 text-2xs leading-relaxed text-warn">
          {t('groups.manualWarning')}
        </p>
      ) : null}

      {error ? (
        <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad">{error}</p>
      ) : null}
    </Modal>
  )
}
