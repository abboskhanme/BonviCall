/**
 * "Queue a survey for every group" — confirmation, and then the outcome.
 *
 * ═══ Why a confirmation at all, and why it does NOT list the groups ════════
 * In a deployment with a bot this button reaches hundreds of chats real
 * customers sit in, and a posted message cannot be taken back. So it is
 * confirmed.
 *
 * It is confirmed from the TREE's aggregate counts and not from a list of
 * names. BonviZvonki's earlier version pulled every group and listed them one
 * by one; at roughly a thousand groups that is neither possible nor useful —
 * nobody reads a thousand-row list before agreeing to it. Two numbers answer
 * the question instead: how many are ready, and how many will be passed over.
 *
 * ═══ In THIS deployment nothing is delivered ══════════════════════════════
 * There is no Telegram bot, so the rows are written and stay queued. The modal
 * says that plainly rather than reporting a send that did not happen.
 */
import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Clock, Info, Send, Users2 } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t, type MessageKey } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'

import {
  treeTotals,
  useBroadcastSurveys,
  useGroupTree,
  type BroadcastResult,
} from './api'

/** A thousand groups can produce hundreds of skips; the rest are counted. */
const SKIP_PREVIEW = 20

/**
 * A skip reason as a word a person reads.
 *
 * An unrecognised code renders as ITSELF rather than as a blank badge: the
 * server can add a reason before the panel knows it, and an English
 * identifier on screen is unmistakable in review where an empty chip is not.
 */
function skipLabel(reason: string): string {
  const key = SKIP_REASON[reason]
  return key ? t(key) : reason
}

const SKIP_REASON: Record<string, MessageKey | undefined> = {
  group_not_bound: 'groups.skipReason.group_not_bound',
  group_inactive: 'groups.skipReason.group_inactive',
  survey_suppressed: 'groups.skipReason.survey_suppressed',
}

export function BroadcastModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const tree = useGroupTree()
  const broadcast = useBroadcastSurveys()
  const [result, setResult] = useState<BroadcastResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setResult(null)
    setError(null)
  }, [open])

  const totals = treeTotals(tree.data)

  if (result) {
    const shown = result.skipped.slice(0, SKIP_PREVIEW)
    const hidden = result.skipped.length - shown.length
    return (
      <Modal
        open={open}
        onOpenChange={(next) => !next && onClose()}
        title={t('groups.broadcastDoneTitle')}
      >
        <div className="flex items-start gap-3 rounded-md bg-good/10 p-3">
          <Check className="mt-0.5 size-4 shrink-0 text-good" aria-hidden />
          <div>
            <p className="text-sm font-medium text-good">
              {t('groups.broadcastCreated', { count: formatCount(result.created) })}
            </p>
            {/* ⚠️ created + reused + skipped == total_groups, always. A partial
                answer sends an admin to the list to count rows. */}
            <p className="mt-1 text-xs leading-relaxed text-muted">
              {t('groups.broadcastTotals', {
                total: result.total_groups,
                created: result.created,
                reused: result.reused,
                skipped: result.skipped.length,
              })}
            </p>
          </div>
        </div>

        {result.delivered === 0 && result.created > 0 ? (
          <div className="flex items-start gap-2 rounded-md bg-warn/10 px-3 py-2 text-2xs leading-relaxed text-warn">
            <Clock className="mt-px size-3.5 shrink-0" aria-hidden />
            <span>{t('groups.notDeliveredHint')}</span>
          </div>
        ) : null}

        {result.reused > 0 ? (
          <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
            {t('groups.broadcastReused', { count: result.reused })}
          </p>
        ) : null}

        {result.skipped.length > 0 ? (
          <div className="rounded-md bg-warn/10 p-3">
            <div className="mb-2 flex items-center gap-1.5 text-2xs font-medium text-warn">
              <AlertTriangle className="size-3.5" aria-hidden />
              {t('groups.broadcastSkipped', { count: result.skipped.length })}
            </div>
            <ul className="max-h-44 space-y-1.5 overflow-y-auto">
              {shown.map((skip) => (
                <li key={skip.group_id} className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="truncate text-text">{skip.title}</span>
                  <Badge tone="warn">{skipLabel(skip.reason)}</Badge>
                </li>
              ))}
            </ul>
            {hidden > 0 ? (
              <p className="mt-2 text-2xs text-muted">
                {t('groups.broadcastSkippedMore', { count: hidden })}
              </p>
            ) : null}
          </div>
        ) : null}
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t('groups.broadcastTitle')}
      description={t('groups.broadcastIrreversible')}
      submitLabel={
        broadcast.status === 'pending'
          ? t('groups.broadcastSending')
          : t('groups.broadcastConfirm', { count: totals.bound })
      }
      submitting={broadcast.status === 'pending'}
      submitDisabled={totals.bound === 0}
      onSubmit={(event) => {
        event.preventDefault()
        setError(null)
        broadcast.mutate(undefined, {
          onSuccess: setResult,
          onError: (failure) => setError(messageForError(failure)),
        })
      }}
    >
      <div className="flex items-start gap-3 rounded-md bg-accent-soft p-3">
        <Users2 className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div>
          {totals.bound > 0 ? (
            <>
              <p className="text-sm font-medium text-text">
                {t('groups.broadcastCount', { count: formatCount(totals.bound) })}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted">
                {t('groups.broadcastPerAgent')}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-warn">{t('groups.broadcastNone')}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">
                {t('groups.broadcastNoneHint')}
              </p>
            </>
          )}
        </div>
      </div>

      {totals.unassigned > 0 ? (
        <div className="flex items-start gap-2 rounded-md bg-warn/10 px-3 py-2 text-2xs leading-relaxed text-warn">
          <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>{t('groups.broadcastWillSkip', { count: totals.unassigned })}</span>
        </div>
      ) : null}

      {/* The whole meaning of the button: the window is ignored. */}
      <p className="flex items-start gap-2 rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
        <Clock className="mt-px size-3.5 shrink-0" aria-hidden />
        {t('groups.broadcastForce')}
      </p>

      {/* And the honest one: nothing will actually reach a customer here. */}
      <p className="flex items-start gap-2 rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden />
        {t('groups.notDeliveredHint')}
      </p>

      {totals.bound > 0 ? (
        <div>
          <span className="text-2xs font-medium uppercase tracking-wide text-muted">
            {t('groups.broadcastRecipients')}
          </span>
          {/* Employees, not groups — fifteen rows rather than a thousand. */}
          <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto text-xs">
            {(tree.data?.agents ?? [])
              .filter((agent) => agent.group_count > 0)
              .sort((a, b) => b.group_count - a.group_count)
              .map((agent) => (
                <li key={agent.agent_id} className="flex items-center gap-2">
                  <span className="truncate text-text">{agent.full_name}</span>
                  <span className="ms-auto shrink-0 tabular-nums text-2xs text-muted">
                    {t('groups.groupCount', { count: agent.group_count })}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      ) : null}

      {error ? (
        <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad">{error}</p>
      ) : null}
    </Modal>
  )
}

/** The page's button. Kept here so the trigger and the dialog stay together. */
export function BroadcastButton({ onOpen }: { onOpen: () => void }) {
  return (
    <Button onClick={onOpen}>
      <Send className="me-1 size-4" aria-hidden />
      {t('groups.broadcast')}
    </Button>
  )
}
