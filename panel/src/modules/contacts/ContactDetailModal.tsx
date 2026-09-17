/**
 * One number, and everything the product knows about it.
 *
 * Ported from BonviZvonki `web/src/modules/contacts/ContactDetailModal.tsx`.
 *
 * ═══ SALES SEAM ═══════════════════════════════════════════════════════════
 * Theirs has four sections; two of them read the SAP partner catalogue and the
 * sales ledger — "SAP katalogi ({n})" with one card per partner, and a sales
 * summary that returns `null` unless the reader holds `sales:read`
 * SEPARATELY from the right to open this card, because those figures are a
 * check carried out ON a salesperson. Neither is ported: the `sales` module is
 * being ported separately and nothing here reads a `sales*` table. The two
 * sections that remain — our own record, and this number's traffic — are the
 * ones this deployment can answer.
 * ═════════════════════════════════════════════════════════════════════════
 */
import { Link } from 'react-router-dom'
import { Trash2 } from 'lucide-react'

import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount, formatDate, formatDuration, formatPhone } from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  KIND_LABEL,
  useContactDetail,
  useDeleteContact,
  type ContactDetail,
  type ContactRow,
} from './api'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-2xs font-medium uppercase tracking-wide text-muted">
        {label}
      </span>
      <span className="min-w-0 truncate text-end text-sm text-text">{children}</span>
    </div>
  )
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: 'bad' }) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2">
      <span className="block text-2xs font-medium uppercase tracking-wide text-muted">
        {label}
      </span>
      <span
        className={cn('block text-sm font-semibold tabular-nums text-text', tone === 'bad' && 'text-bad')}
      >
        {value}
      </span>
    </div>
  )
}

function OtherNumber({ row }: { row: ContactRow }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-md border border-border bg-surface-2 px-2 py-1 text-2xs">
      <span className="truncate">{row.name ?? row.raw_name}</span>
      <span className="font-mono text-muted">
        {formatPhone(row.phone) ?? row.phone_key}
      </span>
    </span>
  )
}

function Body({
  detail,
  canWrite,
  onDeleted,
}: {
  detail: ContactDetail
  canWrite: boolean
  onDeleted: () => void
}) {
  const remove = useDeleteContact()
  const contact = detail.contact
  const calls = detail.calls

  return (
    <div className="space-y-5">
      <section className="space-y-1">
        <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
          {t('contacts.detail.ours')}
        </h3>
        <div className="rounded-md border border-border px-3 py-1">
          {/* The name exactly as the handset had it — never edited, so that
              "why did this become that code?" is answerable from the row. */}
          <Fact label={t('contacts.detail.rawName')}>
            <span>{contact.raw_name}</span>
            <span className="ms-1.5 text-2xs text-muted">
              {t('contacts.detail.rawNameHint')}
            </span>
          </Fact>
          <Fact label={t('contacts.col.phone')}>
            <span className="font-mono">
              {formatPhone(contact.phone) ?? contact.phone_key}
            </span>
          </Fact>
          <Fact label={t('contacts.col.code')}>
            {contact.code ? (
              <span className="font-mono text-accent">{contact.code}</span>
            ) : (
              <span className="text-muted">{EM_DASH}</span>
            )}
          </Fact>
          <Fact label={t('contacts.col.kind')}>
            <Badge>{t(KIND_LABEL[contact.kind])}</Badge>
          </Fact>
          <Fact label={t('contacts.col.source')}>
            <span className="text-muted">{contact.source_file ?? EM_DASH}</span>
          </Fact>
        </div>

        {detail.other_numbers.length > 0 ? (
          <div className="space-y-1.5 pt-1">
            <p className="text-2xs text-muted">
              {t('contacts.detail.otherNumbers', {
                count: detail.other_numbers.length,
              })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {detail.other_numbers.map((row) => (
                <OtherNumber key={row.phone_key} row={row} />
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <section className="space-y-2">
        <h3 className="text-2xs font-semibold uppercase tracking-wide text-muted">
          {t('contacts.detail.calls')}
        </h3>
        {calls === null ? (
          // Null, not zeros: "nobody has ever called this number" is a
          // different statement from "they called and we counted nothing".
          <p className="text-sm text-muted">{t('contacts.detail.noCalls')}</p>
        ) : (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Tile
                label={t('clients.colCalls')}
                value={formatCount(calls.calls_total)}
              />
              <Tile label={t('contacts.detail.inbound')} value={formatCount(calls.inbound)} />
              {/* ⚠️ Incoming and unanswered only — the outgoing half is the
                  customer being busy and is a different fact. */}
              <Tile
                label={t('clients.colMissed')}
                value={formatCount(calls.missed)}
                tone={calls.missed > 0 ? 'bad' : undefined}
              />
              <Tile
                label={t('clients.colTalk')}
                value={formatDuration(calls.talk_seconds)}
              />
            </div>
            {calls.first_call_at && calls.last_call_at ? (
              <p className="text-2xs text-muted">
                {t('contacts.detail.period', {
                  from: formatDate(calls.first_call_at),
                  to: formatDate(calls.last_call_at),
                  count: formatCount(calls.calls_total),
                })}
              </p>
            ) : null}
            {calls.main_agent_name ? (
              <p className="text-2xs text-muted">
                {t('contacts.detail.mainAgent')}: {calls.main_agent_name}
                {calls.agent_count > 1 ? ` (+${calls.agent_count - 1})` : ''}
              </p>
            ) : null}
            <Link
              to={`/clients/${detail.phone_key}`}
              className="inline-block text-xs text-accent underline-offset-2 hover:underline"
            >
              {t('contacts.detail.openClient')}
            </Link>
          </div>
        )}
      </section>

      {/*
        SALES SEAM — the partner-catalogue section and the sales summary go
        here. Both wait on the `sales` module; the sales half additionally
        requires `sales:read`, which is NOT inherited from the right to open
        this card.
      */}

      {canWrite ? (
        <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
          <p className="text-2xs text-muted">{t('contacts.deleteHint')}</p>
          <Button
            variant="ghost"
            size="sm"
            disabled={remove.status === 'pending'}
            onClick={() =>
              remove.mutate(detail.phone_key, { onSuccess: onDeleted })
            }
          >
            <Trash2 className="size-4" aria-hidden />
            {t('contacts.delete')}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function ContactDetailModal({
  phoneKey,
  onClose,
  canWrite,
}: {
  phoneKey: string | null
  onClose: () => void
  canWrite: boolean
}) {
  const detailQuery = useContactDetail(phoneKey)
  const contact = detailQuery.data?.contact

  return (
    <Modal
      open={phoneKey !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title={contact?.name ?? contact?.raw_name ?? formatPhone(phoneKey) ?? EM_DASH}
      description={
        contact?.code
          ? `${contact.code} · ${formatPhone(contact.phone) ?? contact.phone_key}`
          : (formatPhone(phoneKey) ?? undefined)
      }
      className="w-[min(40rem,calc(100vw-2rem))]"
    >
      {phoneKey === null ? null : (
        <QueryBoundary query={detailQuery} skeletonRows={4}>
          {(detail) => (
            <Body detail={detail} canWrite={canWrite} onDeleted={onClose} />
          )}
        </QueryBoundary>
      )}
    </Modal>
  )
}
