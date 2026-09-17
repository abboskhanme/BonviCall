/**
 * One change applied to many groups at once.
 *
 * ⚠️ **Every chunk is reported, and a failed one does not cancel the rest.**
 * The server takes 200 groups per request, so a larger selection is split. If
 * 400 groups are selected and the first 200 save while the second 200 fail, an
 * admin has to be told exactly that — not the single word "error", and not a
 * silent partial success they discover later by counting rows.
 */
import { useEffect, useState } from 'react'
import { AlertTriangle, Check } from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { Modal } from '@/shared/ui/Modal'

import { useBulkPatchGroups, type BulkResult, type Group } from './api'

export type BulkMode = 'agent' | 'clear'

export function BulkAssignModal({
  open,
  mode,
  groups,
  onClose,
  onDone,
}: {
  open: boolean
  mode: BulkMode
  groups: Group[]
  onClose: () => void
  onDone: () => void
}) {
  const bulk = useBulkPatchGroups()
  const agents = useAgentDirectory(open && mode === 'agent')
  const [agentId, setAgentId] = useState('')
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [result, setResult] = useState<BulkResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Reopening must not show the previous run's outcome.
  useEffect(() => {
    if (!open) return
    setAgentId('')
    setProgress(null)
    setResult(null)
    setError(null)
  }, [open])

  const count = groups.length
  const title =
    mode === 'clear'
      ? t('groups.bulkTitleClear', { count })
      : t('groups.bulkTitleAgent', { count })

  if (result) {
    return (
      <Modal
        open={open}
        onOpenChange={(next) => {
          if (!next) {
            onDone()
            onClose()
          }
        }}
        title={t('groups.bulkDoneTitle')}
      >
        <div className="flex items-start gap-3 rounded-md bg-good/10 p-3">
          <Check className="mt-0.5 size-4 shrink-0 text-good" aria-hidden />
          <div>
            <p className="text-sm font-medium text-good">
              {t('groups.bulkUpdated', { count: formatCount(result.updated) })}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              {t('groups.bulkTotals', {
                total: count,
                updated: result.updated,
                failed: result.failed.reduce((sum, item) => sum + item.count, 0),
              })}
            </p>
          </div>
        </div>

        {result.failed.length > 0 ? (
          <div className="rounded-md bg-bad/10 p-3">
            <div className="mb-2 flex items-center gap-1.5 text-2xs font-medium text-bad">
              <AlertTriangle className="size-3.5" aria-hidden />
              {t('groups.bulkFailedChunk', {
                title: result.failed[0]?.title ?? '',
                count: result.failed.reduce((sum, item) => sum + item.count, 0),
              })}
            </div>
            <ul className="space-y-1 text-2xs leading-relaxed text-muted">
              {result.failed.map((failure) => (
                <li key={failure.title}>{failure.message}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={title}
      submitLabel={
        mode === 'clear'
          ? t('groups.bulkConfirmClear', { count })
          : t('groups.bulkConfirmAgent', { count })
      }
      submitting={bulk.status === 'pending'}
      submitDisabled={mode === 'agent' && !agentId}
      onSubmit={(event) => {
        event.preventDefault()
        setError(null)
        bulk.mutate(
          {
            groups,
            patch: { agent_id: mode === 'clear' ? null : agentId },
            onProgress: (done, total) => setProgress({ done, total }),
          },
          {
            onSuccess: setResult,
            onError: (failure) => setError(messageForError(failure)),
          },
        )
      }}
    >
      {mode === 'agent' ? (
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">{t('groups.bulkPickAgent')}</span>
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
        </label>
      ) : (
        <p className="rounded-md bg-surface-2 px-3 py-2 text-xs leading-relaxed text-muted">
          {t('groups.bulkClearExplain')}
        </p>
      )}

      <p className="rounded-md bg-warn/10 px-3 py-2 text-2xs leading-relaxed text-warn">
        {t('groups.manualWarning')}
      </p>

      <div>
        <span className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('groups.bulkAffected')}
        </span>
        <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto text-xs text-text">
          {groups.slice(0, 20).map((group) => (
            <li key={group.id} className="truncate">
              {group.title}
            </li>
          ))}
        </ul>
      </div>

      {progress ? (
        <p className="text-2xs tabular-nums text-muted">
          {t('groups.bulkRunning', { done: progress.done, total: progress.total })}
        </p>
      ) : null}

      {error ? (
        <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad">{error}</p>
      ) : null}
    </Modal>
  )
}
