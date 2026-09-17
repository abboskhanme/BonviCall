/**
 * The decision — the entire point of the review queue.
 *
 * The evidence is repeated here in full so nobody has to go back to the table
 * to answer the question the dialog is asking.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ THE TWO DECISIONS DEMAND DIFFERENT THINGS, and deliberately:
 *
 *   · "Oqlandi" requires a REASON. "I justified it" with no reason says
 *     nothing, and the whole value of the statistic is in the distribution of
 *     reasons — "half of the sales were agreed over Telegram" is a fault in
 *     the SYSTEM, not in the employee.
 *   · "Haqiqatan shubhali" requires a NOTE. That decision has consequences for
 *     a person, so it must not be one click away.
 *
 * ⚠️ `reason` IS SENT ONLY WITH `justified`. The server REFUSES it alongside
 * `confirmed` — a 422 whose `detail.field` is `"reason"` — rather than
 * dropping it. The source dropped it silently, so a manager could pick
 * "Kelib oldi" beside "really suspicious" and watch it disappear. The picker
 * here is not merely hidden for `confirmed`: the field is not sent at all.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import { ShieldCheck, TriangleAlert } from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatDateTime } from '@/shared/lib/format'
import { Modal, ModalField, ModalFields } from '@/shared/ui/Modal'
import { SELECT_CLASS } from '@/shared/ui/filters'

import {
  REASON_LABEL,
  REVIEW_REASONS,
  useReviewSale,
  type ComplianceItem,
  type SaleReviewReason,
  type SaleReviewStatus,
} from './api'
import { RuleBadges, VerdictBadge } from './badges'
import { formatSaleDate, formatUsd } from './saleDate'
import { sellerHint, sellerName, sellerUnlinked } from './seller'

const NOTE_LIMIT = 500

/** Below this a note is not a note. Only `confirmed` requires one. */
const NOTE_MIN = 3

/** One of the two decisions, as a card rather than a radio. */
function ChoiceButton({
  active,
  tone,
  icon: Icon,
  title,
  hint,
  onClick,
}: {
  active: boolean
  tone: 'good' | 'bad'
  icon: typeof ShieldCheck
  title: string
  hint: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'flex items-start gap-2.5 rounded-md border p-3 text-start transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        active
          ? tone === 'good'
            ? 'border-good/40 bg-good/10'
            : 'border-bad/40 bg-bad/10'
          : 'border-border bg-surface hover:bg-surface-2',
      )}
    >
      <Icon
        className={cn(
          'mt-0.5 size-4 shrink-0',
          active ? (tone === 'good' ? 'text-good' : 'text-bad') : 'text-muted',
        )}
        aria-hidden
      />
      <span className="min-w-0">
        <span
          className={cn(
            'block text-xs font-medium',
            active ? (tone === 'good' ? 'text-good' : 'text-bad') : 'text-text',
          )}
        >
          {title}
        </span>
        <span className="mt-0.5 block text-2xs leading-relaxed text-muted">{hint}</span>
      </span>
    </button>
  )
}

/** The facts the decision is taken on, repeated in full. */
function Evidence({ sale, windowDays }: { sale: ComplianceItem; windowDays?: number }) {
  const facts: { label: string; value: string; tone?: 'warn' | 'bad' }[] = [
    { label: t('sales.col.date'), value: formatSaleDate(sale.occurred_on) },
    { label: t('sales.col.amountUsd'), value: formatUsd(sale.amount_usd) },
    {
      label: t('sales.col.agent'),
      value: [sellerName(sale) ?? t('sales.noAgent'), sellerHint(sale)].filter(Boolean).join(' · '),
      tone: sellerUnlinked(sale) ? 'warn' : undefined,
    },
    { label: t('sales.col.phone'), value: sale.phone ?? EM_DASH },
    {
      label: t('sales.col.lastCall'),
      value: sale.last_call_at
        ? [
            formatDateTime(sale.last_call_at),
            sale.last_call_agent,
            sale.days_before !== null && sale.days_before !== undefined
              ? t('sales.daysBefore', { count: sale.days_before })
              : null,
          ]
            .filter(Boolean)
            .join(' · ')
        : t('sales.noCallEver'),
      tone: sale.last_call_at ? undefined : 'bad',
    },
    {
      label: t('sales.col.previousSale'),
      value: sale.previous_sale_on
        ? t('sales.betweenCalls', {
            date: formatSaleDate(sale.previous_sale_on),
            count: sale.calls_between,
          })
        : t('sales.noPreviousSale'),
      tone: sale.previous_sale_on && sale.calls_between === 0 ? 'warn' : undefined,
    },
    {
      label: t('sales.col.callsTotal'),
      value: t('sales.callsTotal', { count: sale.calls_total }),
      tone: sale.calls_total === 0 ? 'bad' : undefined,
    },
    { label: t('sales.col.operation'), value: sale.external_id },
  ]

  return (
    <div className="rounded-md bg-surface-2 p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <VerdictBadge verdict={sale.verdict} skipReason={sale.skip_reason} />
        <RuleBadges rules={sale.broken_rules} windowDays={windowDays} />
      </div>
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0">
            <dt className="text-2xs text-muted">{fact.label}</dt>
            <dd
              className={cn(
                'text-xs text-text',
                fact.tone === 'bad' && 'font-medium text-bad',
                fact.tone === 'warn' && 'font-medium text-warn',
              )}
            >
              {fact.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function ReviewModal({
  sale,
  windowDays,
  onClose,
}: {
  /** `null` closes the dialog. */
  sale: ComplianceItem | null
  windowDays?: number
  onClose: () => void
}) {
  const review = useReviewSale()

  const [status, setStatus] = useState<SaleReviewStatus>('justified')
  const [reason, setReason] = useState<SaleReviewReason>('walk_in')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  const saleId = sale?.id ?? null
  /* Reset on every open, and to the EXISTING decision when there is one: a
     manager most often reopens this to correct the note, and a blank form
     would make them type it again. */
  useEffect(() => {
    if (!saleId) return
    setStatus(sale?.review?.status ?? 'justified')
    setReason(sale?.review?.reason ?? 'walk_in')
    setNote(sale?.review?.note ?? '')
    setError(null)
    review.reset()
    // `review` is a new object on every render; watching it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saleId])

  const justified = status === 'justified'
  const valid = justified ? Boolean(reason) : note.trim().length >= NOTE_MIN
  const saving = review.status === 'pending'

  function submit() {
    if (!sale || !valid) return
    setError(null)
    review.mutate(
      {
        saleId: sale.id,
        status,
        // ⚠️ NOT SENT AT ALL with `confirmed`. The server answers 422 for it,
        // and a field the UI sends only to have it refused is a dead control.
        ...(justified ? { reason } : {}),
        note: note.trim() || null,
      },
      {
        onSuccess: onClose,
        onError: (failure) => setError(messageForError(failure)),
      },
    )
  }

  return (
    <Modal
      open={sale !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t('sales.decision.title')}
      description={
        sale ? [sale.partner_name, sale.partner_code].filter(Boolean).join(' · ') : undefined
      }
      className="w-[min(40rem,calc(100vw-2rem))]"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      submitLabel={saving ? t('sales.decision.saving') : t('sales.decision.save')}
      submitting={saving}
      submitDisabled={!valid}
      danger={!justified}
    >
      {sale ? (
        <ModalFields>
          <Evidence sale={sale} windowDays={windowDays} />

          {/* ⚠️ Two buttons rather than a segmented control: these are not two
              views of one thing, they are two decisions with different
              consequences. The icon and the colour say so. */}
          <div className="space-y-2">
            <span className="text-xs font-medium text-muted">
              {t('sales.decision.question')}
            </span>
            <div className="grid gap-2 sm:grid-cols-2">
              <ChoiceButton
                active={justified}
                tone="good"
                icon={ShieldCheck}
                title={t('sales.review.justified')}
                hint={t('sales.decision.justifiedHint')}
                onClick={() => setStatus('justified')}
              />
              <ChoiceButton
                active={!justified}
                tone="bad"
                icon={TriangleAlert}
                title={t('sales.review.confirmed')}
                hint={t('sales.decision.confirmedHint')}
                onClick={() => setStatus('confirmed')}
              />
            </div>
          </div>

          {justified ? (
            <ModalField htmlFor="sale-reason" label={t('sales.decision.reason')}>
              <select
                id="sale-reason"
                className={cn(SELECT_CLASS, 'w-full')}
                value={reason}
                onChange={(event) => setReason(event.target.value as SaleReviewReason)}
              >
                {REVIEW_REASONS.map((value) => (
                  <option key={value} value={value}>
                    {t(REASON_LABEL[value])}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-2xs leading-relaxed text-muted">
                {t('sales.decision.reasonHint')}
              </p>
            </ModalField>
          ) : null}

          <ModalField
            htmlFor="sale-note"
            label={justified ? t('sales.decision.note') : t('sales.decision.noteRequired')}
          >
            <textarea
              id="sale-note"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value.slice(0, NOTE_LIMIT))}
              placeholder={t('sales.decision.notePlaceholder')}
              className={cn(
                'w-full resize-y rounded-md border border-border bg-surface px-3 py-2',
                'text-sm leading-relaxed text-text placeholder:text-muted',
                'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20',
              )}
            />
            <p className="mt-1 text-2xs text-muted">
              {t('sales.decision.noteCount', { count: note.length, limit: NOTE_LIMIT })}
            </p>
          </ModalField>

          {sale.review ? (
            <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
              {t('sales.decision.previous', {
                who: sale.review.reviewed_by ?? EM_DASH,
                when: sale.review.reviewed_at
                  ? formatDateTime(sale.review.reviewed_at)
                  : EM_DASH,
              })}
            </p>
          ) : null}

          {error ? (
            <p className="rounded-md bg-bad/10 px-3 py-2 text-xs text-bad" role="alert">
              {error}
            </p>
          ) : null}
        </ModalFields>
      ) : null}
    </Modal>
  )
}
