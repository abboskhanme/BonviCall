/**
 * The daily message — assembled and SHOWN, never sent.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ NOTHING LEAVES THIS DEPLOYMENT, BY DESIGN. Telegram delivery is a logging
 * seam with no network access behind it: the only transport implementation
 * writes a log line, so the answer always comes back `sent: false` with
 * `reason: "send_failed"` and `error: "no_transport_configured"`.
 *
 * That is NOT a failure for this screen to route around. The button exists to
 * answer one question — "what would go out?" — and the answer is the `text`
 * field, which is returned whatever `sent` says. So the dialog shows the text
 * and states plainly that nothing was sent, and carries NO control that would
 * try to send it. A retry button here would be a control that cannot work, and
 * a red error box would report a fault where there is a deliberate design.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ⚠️ THE DAY IS THE LAST IMPORTED ONE, not yesterday. The SAP export arrives by
 * hand and is usually behind, so the message covers the most recent day there
 * is data for — and the dialog says which, or the reader would take an
 * unfamiliar date for a fault.
 */
import { Info, Send } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t, type MessageKey } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { Modal } from '@/shared/ui/Modal'

import { useDigestTest, type DigestTest } from './api'
import { formatSaleDate } from './saleDate'

/** The transport's own ceiling. */
const CHAR_LIMIT = 4096

/**
 * Why nothing went out.
 *
 * Every one of these is a STATE, not an error: the switch is off, no chat has
 * been named, there are no sales, nothing new since the last message, or —
 * always, here — there is no transport at all.
 */
const REASON_NOTE: Record<string, MessageKey> = {
  disabled: 'sales.digest.reason.disabled',
  no_chat: 'sales.digest.reason.no_chat',
  no_sales: 'sales.digest.reason.no_sales',
  no_new_import: 'sales.digest.reason.no_new_import',
  send_failed: 'sales.digest.reason.send_failed',
}

function Result({ result }: { result: DigestTest }) {
  const note = result.reason ? REASON_NOTE[result.reason] : undefined

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted">
        {result.day ? (
          <span className="tabular-nums">
            {t('sales.digest.day', { day: formatSaleDate(result.day) })}
          </span>
        ) : null}
        <span className="tabular-nums">
          {t('sales.digest.chars', {
            count: formatCount(result.chars),
            limit: formatCount(CHAR_LIMIT),
          })}
        </span>
      </div>

      {/* ⚠️ A NEUTRAL NOTE, NOT AN ERROR BOX. Nothing went wrong: this
          deployment has no transport, and that is the documented arrangement. */}
      <p className="flex items-start gap-2 rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          {t('sales.digest.notSent')}
          {note ? ` ${t(note)}` : ''}
        </span>
      </p>

      {/* The message itself, exactly as it was composed — whitespace and line
          breaks included, because that is what would be delivered. */}
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-surface-2 px-3 py-2 font-mono text-xs leading-relaxed text-text">
        {result.text}
      </pre>
    </div>
  )
}

export function DigestModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const digest = useDigestTest()
  const running = digest.status === 'pending'

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) digest.reset()
        onOpenChange(next)
      }}
      title={t('sales.digest.title')}
      description={t('sales.digest.subtitle')}
      className="w-[min(44rem,calc(100vw-2rem))]"
      onSubmit={(event) => {
        event.preventDefault()
        digest.mutate()
      }}
      submitLabel={running ? t('sales.digest.running') : t('sales.digest.compose')}
      submitting={running}
    >
      <div className="space-y-4">
        {digest.error ? (
          <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad" role="alert">
            {messageForError(digest.error)}
          </p>
        ) : null}

        {digest.data ? (
          <Result result={digest.data} />
        ) : (
          <p className="flex items-start gap-2 rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
            <Send className="mt-px size-3.5 shrink-0" aria-hidden />
            {t('sales.digest.hint')}
          </p>
        )}
      </div>
    </Modal>
  )
}
