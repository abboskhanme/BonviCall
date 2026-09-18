/**
 * The sale card — what opens when a row is clicked.
 *
 * ⚠️ WHY IT EXISTS. The table row carries status codes only (`R1`,
 * "Shubhali"); there is no room for detail. Before recording a decision the
 * manager has to see the SALE: the date, SAP's operation and document numbers,
 * the amount in both currencies, the employee, the customer code.
 *
 * ⚠️ THE CARD IS NEVER EMPTY. The source once showed only the chain here, and
 * for a customer with no phone it could not build one — so for a walk-in buyer
 * the whole dialog was a single sentence saying it had nothing to draw, while
 * every fact about the sale was already in the response.
 *
 * ⚠️ THE CHAIN IS ONLY DRAWN FOR A CUSTOMER WE CAN IDENTIFY. A walk-in buyer
 * passes under a shared code and has no number of their own, so no
 * conversation can be tied to the sale. An empty list there would be the false
 * conclusion "nobody ever called them".
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ THE CHAIN COMES FROM THE SERVER, ALREADY INTERLEAVED AND ALREADY ORDERED
 * — this is the port's largest structural change. The source built it in the
 * browser from two separate requests (`/clients/{key}/calls` and
 * `/clients/{key}/sales`), merged them and sorted, which meant:
 *
 *   · the rule "on one day the conversation comes before the sale" was
 *     re-implemented on the client, as a hack that pushed a sale to 23:59:59
 *     of its own day. Two copies of one rule, and the browser's copy could
 *     drift from the one the verdict is actually computed with;
 *   · the call list was capped at 200 rows NEWEST FIRST, so when it was cut
 *     the conversations that went missing were the ones just BEFORE the sale —
 *     precisely the evidence the card exists to show.
 *
 * `GET /sales/compliance/timeline` returns both kinds as ONE type told apart
 * by `kind`, in order, with the same-day rule applied server-side. Nothing
 * here re-sorts it.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ⚠️ ±30 DAYS. The whole history would be noise; a month around the sale is
 * much wider than the rule's own window (usually 3 days) and nearly always
 * contains the previous sale, which is what R2 turns on.
 *
 * ⚠️ WHOSE PHONE — SAID OUT LOUD. A bare "Telefon" label invites the reader to
 * take it for the employee's number. It is the CUSTOMER's, it comes from the
 * catalogue, and conversations are matched on it.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CalendarClock,
  Eye,
  EyeOff,
  Info,
  PhoneIncoming,
  PhoneOutgoing,
  ShoppingBag,
  TriangleAlert,
} from 'lucide-react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import {
  EM_DASH,
  formatCount,
  formatDateTime,
  formatDuration,
  formatPhone,
  formatTime,
} from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { Field, FieldGrid } from '@/shared/ui/detail'
import { Modal } from '@/shared/ui/Modal'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  useExcludePartner,
  useSaleTimeline,
  type ClientKind,
  type ComplianceItem,
  type PartnerExclusion,
  type TimelineClient,
  type TimelineEvent,
  type TimelineQuery,
} from './api'
import { ReviewBadge, RuleBadges, SkipBadge, VerdictBadge } from './badges'
import { saleReason } from './reason'
import { formatSaleDate, formatUsd, shiftDay } from './saleDate'
import { sellerHint, sellerName, sellerUnlinked } from './seller'

/** The window drawn around the sale, in each direction. */
const AROUND_DAYS = 30

/**
 * How many customers the chain request may return.
 *
 * The search is by customer CODE, which all but always matches one. A handful
 * rather than one so that a code which is a prefix of another still finds the
 * exact row — picked out below by an exact comparison rather than by position.
 */
const MAX_CLIENTS = 5

/** One dated line in the chain. */
function Line({
  at,
  mark,
  className,
  children,
}: {
  at: string
  mark: React.ReactNode
  className?: string
  children: React.ReactNode
}) {
  return (
    <li className={cn('flex items-start gap-3 rounded-md px-3 py-2', className)}>
      <span className="w-24 shrink-0 pt-0.5 text-xs tabular-nums text-muted">
        {formatSaleDate(at)}
      </span>
      {mark}
      <div className="min-w-0 flex-1">{children}</div>
    </li>
  )
}

function CallLine({ event, canOpenCall }: { event: TimelineEvent; canOpenCall: boolean }) {
  /* ⚠️ `incoming`, NOT `inbound`. The wire vocabulary is this product's own
     (`core/enums.py::CallDirection`, "Ours, not BonviZvonki's"), and the
     service export is the ONE place the two are mapped onto each other. The
     port carried the old word across and the comparison was therefore always
     false: every call on this card was drawn as outgoing — the icon, the
     colour and the word — and an unanswered INCOMING call said "the customer
     did not pick up" when it was ours that went unanswered.

     `TimelineEvent.direction` is a plain string on the wire, because on a SALE
     row the same field carries SAP's product line, so neither spelling is a
     compile error here. The test below is what holds it. */
  const incoming = event.direction === 'incoming'
  const Icon = incoming ? PhoneIncoming : PhoneOutgoing

  return (
    <Line
      at={event.at}
      className="bg-surface-2"
      mark={
        <Icon
          className={cn('mt-0.5 size-4 shrink-0', incoming ? 'text-accent' : 'text-good')}
          aria-hidden
        />
      }
    >
      <div className="truncate text-sm font-medium">
        {/* The recording is one click away where the reader may open it. The
            source printed a name and a time with nothing behind them. */}
        {canOpenCall && event.call_id ? (
          <Link to={`/calls/${event.call_id}`} className="text-accent hover:underline">
            {t('sales.card.call')}
          </Link>
        ) : (
          t('sales.card.call')
        )}
        {event.agent_name ? <span className="text-muted"> · {event.agent_name}</span> : null}
      </div>
      <div className="truncate text-2xs tabular-nums text-muted">
        {formatTime(event.at)}
        {' · '}
        {incoming ? t('sales.card.dirInbound') : t('sales.card.dirOutbound')}
        {' · '}
        {/* An unanswered call lasted 0 seconds and printing "00:00" would read
            as a conversation that happened and said nothing. */}
        {event.answered === false
          ? incoming
            ? t('sales.card.noAnswer')
            : t('sales.card.notPicked')
          : formatDuration(event.duration_sec)}
      </div>
    </Line>
  )
}

function SaleLine({ event, current }: { event: TimelineEvent; current: boolean }) {
  /* R2 — "no conversation between two sales". That case is the whole point of
     the chain, so it is a warning rather than a grey note. */
  const gap = (event.broken_rules ?? []).includes('R2')

  return (
    <Line
      at={event.at}
      className={cn(current ? 'bg-accent-soft' : 'bg-surface-2')}
      mark={
        <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-sm bg-accent-soft text-accent">
          <ShoppingBag className="size-3" aria-hidden />
        </span>
      }
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-sm font-medium">
          {t('sales.card.sale')}
          <span className="text-muted"> · </span>
          <span className="tabular-nums">{formatUsd(event.amount_usd)}</span>
        </span>
        {event.verdict ? (
          <VerdictBadge verdict={event.verdict} />
        ) : null}
        <RuleBadges rules={event.broken_rules ?? []} />
        {current ? (
          <span className="inline-flex">
            <Badge tone="accent" className="whitespace-nowrap">
              {t('sales.card.thisSale')}
            </Badge>
          </span>
        ) : null}
      </div>
      {event.doc_number || event.external_id ? (
        <div className={cn('mt-0.5 truncate text-2xs', gap ? 'text-warn' : 'text-muted')}>
          {[
            event.doc_number ? `${t('sales.col.document')} ${event.doc_number}` : null,
            event.external_id ? `${t('sales.col.operation')} ${event.external_id}` : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </div>
      ) : null}
    </Line>
  )
}

/**
 * "This customer is outside our sales control" — the action, written once.
 *
 * ⚠️ WHY IT EXISTS. With some contractors the work never goes through a call
 * at all (a contract, a tender, another department runs it). Their sales sit
 * in the main list and are counted suspicious after every import, and the
 * manager justifies the same rows again and again. An excluded customer's
 * sales move to the out-of-scope section — they are NOT deleted.
 *
 * ⚠️ THE CONFIRMATION IS NOT `window.confirm`. A browser dialog steals focus
 * inside a modal, cannot be translated and cannot be styled. It is asked here,
 * where the action is.
 *
 * ⚠️ THE NUMBER OF SALES IS NOT IN THE CONFIRMATION, deliberately. Only the
 * server knows it and the answer arrives AFTER the action, so putting it in
 * the prompt would need a request nobody asked for. The prompt says the action
 * is REVERSIBLE — which is the actual fear — and the number appears in the
 * result line.
 *
 * ⚠️ THE STATE IS LOCAL. Which way the button reads comes from the row's own
 * `partner_excluded`, which rides on every list row for exactly this: without
 * it the card would open saying "Exclude" for a customer already excluded, and
 * there would be no way back from this screen.
 */
function PartnerExclusionAction({
  code,
  name,
  initialExcluded,
}: {
  code: string
  name?: string | null
  initialExcluded: boolean
}) {
  const exclude = useExcludePartner()
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<PartnerExclusion | null>(null)
  const [error, setError] = useState<string | null>(null)

  const excluded = result?.excluded ?? initialExcluded
  const busy = exclude.status === 'pending'

  /* The confirmation closes whatever the request does: a row frozen in the
     confirming state leaves the reader unable to tell whether it happened.
     The failure gets its own line. */
  function apply(next: boolean) {
    setError(null)
    setConfirming(false)
    exclude.mutate(
      { code, excluded: next },
      {
        onSuccess: (data) => setResult(data),
        onError: (failure) => setError(messageForError(failure)),
      },
    )
  }

  return (
    <div className="flex flex-col items-start gap-2">
      {confirming ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md bg-bad/10 px-3 py-2">
          <p className="min-w-0 max-w-sm text-2xs leading-relaxed text-bad">
            {t('sales.exclusion.confirm', { client: name || code })}
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => setConfirming(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" disabled={busy} onClick={() => apply(true)}>
              {t('sales.exclusion.yes')}
            </Button>
          </div>
        </div>
      ) : excluded ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex" title={t('sales.exclusion.excludedHint')}>
            <Badge tone="bad" className="whitespace-nowrap">
              <EyeOff className="me-1 size-3" aria-hidden />
              {t('sales.exclusion.excluded')}
            </Badge>
          </span>
          {/* Putting a customer back is harmless, so it is not confirmed. */}
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => apply(false)}>
            <Eye className="size-3.5" aria-hidden />
            {t('sales.exclusion.include')}
          </Button>
        </div>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          title={t('sales.exclusion.hint')}
          onClick={() => setConfirming(true)}
        >
          <EyeOff className="size-3.5" aria-hidden />
          {t('sales.exclusion.action')}
        </Button>
      )}

      {/* How many sales moved — the action's real cost, and knowable only
          afterwards. */}
      {result && !error ? (
        <p className="max-w-sm text-2xs leading-relaxed text-muted">
          {t(
            result.excluded ? 'sales.exclusion.doneExcluded' : 'sales.exclusion.doneIncluded',
            { count: result.sales },
          )}
        </p>
      ) : null}

      {error ? <p className="max-w-sm text-2xs leading-relaxed text-bad">{error}</p> : null}
    </div>
  )
}

/** The chain, once the response is in. */
function Chain({
  client,
  saleId,
  truncated,
  canOpenCall,
}: {
  client: TimelineClient | undefined
  saleId: string
  truncated: boolean
  canOpenCall: boolean
}) {
  const events = client?.events ?? []

  if (events.length === 0) {
    return (
      <p className="rounded-md bg-surface-2 px-3 py-2 text-xs leading-relaxed text-muted">
        {t('sales.card.empty', { count: AROUND_DAYS })}
      </p>
    )
  }

  return (
    <>
      {/* ⚠️ A CUT LIST NEVER GOES UNMENTIONED. A reader who does not know the
          chain is incomplete concludes "there was no conversation in between"
          — when there was one, and it simply was not drawn. */}
      {truncated ? (
        <p className="mb-2 rounded-md bg-warn/10 px-3 py-2 text-2xs leading-relaxed text-warn">
          {t('sales.card.truncated')}
        </p>
      ) : null}

      <ol className="space-y-1.5">
        {events.map((event, index) =>
          event.kind === 'call' ? (
            <CallLine
              key={`call-${event.call_id ?? index}`}
              event={event}
              canOpenCall={canOpenCall}
            />
          ) : (
            <SaleLine
              key={`sale-${event.sale_id ?? index}`}
              event={event}
              current={event.sale_id === saleId}
            />
          ),
        )}
      </ol>

      {/* The assumption is stated. A screen that hides the rule it is ordered
          by cannot be trusted about the order. */}
      <p className="mt-2 rounded-md bg-surface-2 px-3 py-2 text-xs leading-relaxed text-muted">
        {t('sales.card.noTime')}
      </p>
    </>
  )
}

export function SaleCardModal({
  sale,
  windowDays,
  walkInLimit,
  clientKind = 'regular',
  outOfScope = false,
  canOpenCall,
  canExclude,
  onClose,
  onReview,
}: {
  /** `null` closes the dialog and stops the request. */
  sale: ComplianceItem | null
  windowDays?: number
  /** The ticket limit, from the REPORT — never copied into the panel, so the
   *  badge follows the setting on its own. */
  walkInLimit?: number | null
  clientKind?: ClientKind
  outOfScope?: boolean
  canOpenCall: boolean
  /** `settings:write`. Without it the exclusion action is not drawn. */
  canExclude: boolean
  onClose: () => void
  /** `calls:note`. Without it there is no decision button. */
  onReview?: (sale: ComplianceItem) => void
}) {
  /* A customer with no phone key cannot have a chain, and asking for one would
     be a request whose only possible answer is "nothing". */
  const linked = Boolean(sale?.phone_key)

  /**
   * ⚠️ THE CHAIN IS ASKED FOR THIS CUSTOMER AND THIS WINDOW ONLY.
   *
   * The page's own employee, branch and search filters are deliberately NOT
   * passed on: they narrow the LIST, and a chain narrowed the same way would
   * be missing exactly the conversations that explain the verdict. The section
   * filters ARE passed, because an excluded customer's history is only
   * reachable with them.
   *
   * `only_suspicious: false` is essential — its default is `true`, and a clean
   * customer would otherwise come back with no chain at all.
   */
  const query: TimelineQuery = {
    client_kind: clientKind,
    out_of_scope: outOfScope,
    only_suspicious: false,
    max_clients: MAX_CLIENTS,
    search: sale?.partner_code ?? '',
    ...(sale
      ? {
          date_from: shiftDay(sale.occurred_on, -AROUND_DAYS),
          date_to: shiftDay(sale.occurred_on, AROUND_DAYS),
        }
      : {}),
  }
  const timeline = useSaleTimeline(query, Boolean(sale) && linked)

  return (
    <Modal
      open={sale !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t('sales.card.title')}
      description={
        /* ⚠️ THE PHONE IS NOT HERE. On the subtitle line it sat unlabelled and
           there was no way to tell whose number it was. It is below, under
           "Mijoz telefoni". */
        sale ? [sale.partner_name, sale.partner_code].filter(Boolean).join(' · ') : undefined
      }
      className="w-[min(52rem,calc(100vw-2rem))]"
      onSubmit={
        sale && onReview
          ? (event) => {
              event.preventDefault()
              onReview(sale)
            }
          : undefined
      }
      submitLabel={t('sales.card.decide')}
    >
      {sale ? (
        <div className="space-y-5">
          {/* ── The headline: date, amount, status ──────────
              The two biggest figures first — they are what the dialog is
              opened for. */}
          <section className="rounded-md bg-surface-2 p-4">
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
              <div className="min-w-0">
                <p className="text-2xs font-medium uppercase tracking-wide text-muted">
                  {t('sales.col.date')}
                </p>
                <p className="mt-1 text-xl font-semibold leading-tight tabular-nums text-text">
                  {formatSaleDate(sale.occurred_on)}
                </p>
                {/* The operation number: without it the evidence cannot be
                    checked in SAP by hand at all. */}
                <p className="mt-1.5 truncate text-xs tabular-nums text-muted">
                  {t('sales.col.operation')} · {sale.external_id}
                </p>
              </div>

              <div className="min-w-0 text-end">
                <p className="text-2xs font-medium uppercase tracking-wide text-muted">
                  {t('sales.col.amountUsd')}
                </p>
                <p
                  className={cn(
                    'mt-1 text-3xl font-semibold leading-tight tabular-nums',
                    sale.over_limit ? 'text-warn' : 'text-text',
                  )}
                >
                  {formatUsd(sale.amount_usd)}
                </p>
                {sale.currency !== 'USD' && sale.amount !== null && sale.amount !== undefined ? (
                  <p className="mt-1.5 truncate text-xs tabular-nums text-muted">
                    {formatCount(Math.round(sale.amount))} {sale.currency}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <VerdictBadge verdict={sale.verdict} skipReason={sale.skip_reason} />
              {sale.skip_reason ? <SkipBadge reason={sale.skip_reason} /> : null}
              <RuleBadges rules={sale.broken_rules} windowDays={windowDays} />
              {sale.over_limit ? (
                <span
                  className="inline-flex"
                  title={
                    walkInLimit !== null && walkInLimit !== undefined
                      ? t('sales.card.overLimitHint', { limit: formatUsd(walkInLimit) })
                      : undefined
                  }
                >
                  <Badge tone="warn" className="whitespace-nowrap">
                    <TriangleAlert className="me-1 size-3" aria-hidden />
                    {t('sales.card.overLimit')}
                  </Badge>
                </span>
              ) : null}
              <span className="ms-auto">
                <ReviewBadge review={sale.review} />
              </span>
            </div>

            {/* "Why" — one sentence, assembled from the evidence. */}
            <p className="mt-3.5 text-xs leading-relaxed text-muted">
              {saleReason(sale, windowDays)}
            </p>
          </section>

          {/* ── The sale itself ──────────────────────────────── */}
          <section className="space-y-3">
            <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
              {t('sales.card.facts')}
            </h3>
            <FieldGrid>
              <Field label={t('sales.col.client')} value={sale.partner_name || EM_DASH} />
              <Field label={t('sales.col.code')} value={sale.partner_code} mono />
              {/* ⚠️ The word "customer" in the label is deliberate: alone,
                  "Telefon" invites the reader to take it for the employee's
                  number. It comes from the catalogue and conversations are
                  matched on it. */}
              <Field
                label={t('sales.col.phone')}
                value={formatPhone(sale.phone) ?? EM_DASH}
                mono
              />
              <Field label={t('sales.col.agent')}>
                <span
                  className={cn(
                    'block',
                    sellerName(sale) ? undefined : 'font-medium text-warn',
                  )}
                >
                  {sellerName(sale) ?? t('sales.noAgent')}
                </span>
                {sellerHint(sale) ? (
                  <span
                    className={cn(
                      'mt-0.5 block text-xs',
                      sellerUnlinked(sale) ? 'text-warn' : 'text-muted',
                    )}
                  >
                    {sellerHint(sale)}
                  </span>
                ) : null}
              </Field>
              <Field label={t('sales.col.direction')} value={sale.direction || EM_DASH} />
              <Field
                label={t('sales.col.amount')}
                value={
                  sale.amount !== null && sale.amount !== undefined
                    ? `${formatCount(Math.round(sale.amount))} ${sale.currency}`
                    : EM_DASH
                }
                mono
              />
              {/* The document number is NOT the operation number: the manager
                  finds the piece of paper by this one, while the operation
                  number is our idempotency key. */}
              <Field label={t('sales.col.document')} value={sale.doc_number || EM_DASH} mono />
            </FieldGrid>

            {/* ⚠️ THE ACTION SITS UNDER THE CUSTOMER CODE, not beside the
                decision button. It works on the CUSTOMER, not on this sale:
                every sale under this code changes section. Next to "record a
                decision" that distinction would be invisible.

                `key` is the code so that moving to another sale without
                closing the dialog does not leave the previous customer's local
                state behind. */}
            {canExclude ? (
              <PartnerExclusionAction
                key={sale.partner_code}
                code={sale.partner_code}
                name={sale.partner_name}
                initialExcluded={sale.partner_excluded}
              />
            ) : null}
          </section>

          {/* ── The conversation evidence ────────────────────── */}
          <section className="space-y-3">
            <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
              {t('sales.card.evidence')}
            </h3>
            {linked ? (
              <FieldGrid>
                <Field label={t('sales.col.lastCall')}>
                  {sale.last_call_at ? (
                    canOpenCall && sale.last_call_id ? (
                      <Link
                        to={`/calls/${sale.last_call_id}`}
                        className="font-mono text-accent hover:underline"
                      >
                        {formatDateTime(sale.last_call_at)}
                      </Link>
                    ) : (
                      <span className="font-mono">{formatDateTime(sale.last_call_at)}</span>
                    )
                  ) : (
                    <span className="font-medium text-bad">{t('sales.noCallEver')}</span>
                  )}
                </Field>
                <Field
                  label={t('sales.col.lastCallAgent')}
                  value={
                    sale.last_call_at
                      ? [
                          sale.last_call_agent ?? EM_DASH,
                          sale.days_before !== null && sale.days_before !== undefined
                            ? t('sales.daysBefore', { count: sale.days_before })
                            : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')
                      : EM_DASH
                  }
                />
                <Field label={t('sales.col.previousSale')}>
                  <span
                    className={cn(
                      sale.previous_sale_on && sale.calls_between === 0
                        ? 'font-medium text-warn'
                        : undefined,
                    )}
                  >
                    {sale.previous_sale_on
                      ? t('sales.betweenCalls', {
                          date: formatSaleDate(sale.previous_sale_on),
                          count: sale.calls_between,
                        })
                      : t('sales.noPreviousSale')}
                  </span>
                </Field>
                <Field label={t('sales.col.callsTotal')}>
                  <span className={cn(sale.calls_total === 0 ? 'font-medium text-bad' : undefined)}>
                    {t('sales.callsTotal', { count: sale.calls_total })}
                  </span>
                </Field>
              </FieldGrid>
            ) : (
              /* With no number the evidence CANNOT be built, and that is not a
                 fault — it is the very reason the verdict is "could not be
                 checked". So: a note, not an empty list and not a row of
                 zeroes, which would read as an accusation. */
              <div className="flex items-start gap-2.5 rounded-md bg-surface-2 px-3 py-2">
                <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                <div className="min-w-0">
                  <p className="text-sm text-text">{t('sales.card.noPhone')}</p>
                  {sale.skip_reason === 'generic_code' ? (
                    <p className="mt-1 text-xs leading-relaxed text-muted">
                      {t('sales.skip.generic_code')}
                    </p>
                  ) : null}
                  {sale.skip_reason === 'no_phone' ? (
                    <p className="mt-1 text-xs leading-relaxed text-muted">
                      {t('sales.skip.no_phone')}
                    </p>
                  ) : null}
                </div>
              </div>
            )}
          </section>

          {/* ── The decision already on record ───────────────── */}
          {sale.review ? (
            <section className="space-y-3">
              <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
                {t('sales.card.decision')}
              </h3>
              <div className="rounded-md bg-surface-2 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ReviewBadge review={sale.review} />
                  <span className="ms-auto text-xs text-muted">
                    {t('sales.decision.by', {
                      who: sale.review.reviewed_by ?? EM_DASH,
                      when: sale.review.reviewed_at
                        ? formatDateTime(sale.review.reviewed_at)
                        : EM_DASH,
                    })}
                  </span>
                </div>
                {sale.review.note ? (
                  <p className="mt-2.5 text-sm leading-relaxed text-text">
                    «{sale.review.note}»
                  </p>
                ) : null}
              </div>
            </section>
          ) : null}

          {/* ── The chain ─────────────────────────────────────
              Only for a customer we can identify: without a number there is
              nothing to draw, and an empty list would read as "never spoken
              to". */}
          {linked ? (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <CalendarClock className="size-4 shrink-0 text-muted" aria-hidden />
                <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
                  {t('sales.card.timeline')}
                </h3>
                <span className="ms-auto truncate text-xs text-muted">
                  {t('sales.card.window', { count: AROUND_DAYS })}
                </span>
              </div>
              <QueryBoundary query={timeline} skeletonRows={5}>
                {(data) => (
                  <Chain
                    client={
                      // Picked by an exact code match rather than by position:
                      // the search is a text match and a code can be another
                      // code's prefix.
                      (data.clients ?? []).find(
                        (row) => row.partner_code === sale.partner_code,
                      ) ?? (data.clients ?? [])[0]
                    }
                    saleId={sale.id}
                    truncated={data.truncated}
                    canOpenCall={canOpenCall}
                  />
                )}
              </QueryBoundary>
            </section>
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}
