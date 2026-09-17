/**
 * `/contacts` — the phone-key dictionary harvested from the handsets.
 *
 * Ported from BonviZvonki `web/src/modules/contacts/ContactsPage.tsx`.
 *
 * ═══ WHY IT IS A SECTION OF ITS OWN ═══════════════════════════════════════
 * `/clients` is assembled from calls and answers "who have we spoken to, and
 * how much". This answers a different question: what is this number called,
 * does it carry a customer code, and is it even a customer at all. Squeezing
 * the two onto one screen confuses both.
 *
 * ═══ SALES SEAM ═══════════════════════════════════════════════════════════
 * Theirs is a TWO-SIDED table — our phonebook on the left, the SAP partner
 * catalogue on the right, with a match status between them and a fifth
 * pseudo-status for "in the catalogue but in nobody's phone". Four of their
 * stat cards count those statuses. None of it is ported: the `sales` module is
 * being ported separately and nothing here reads a `sales*` table. The
 * left-hand side is the whole of this screen, and the cards count what this
 * deployment can actually answer — how many rows carry a code, and what kind
 * each contact is.
 * ═════════════════════════════════════════════════════════════════════════
 *
 * Access: `settings:read` to read, `settings:write` to change — the same gate
 * the other number→meaning dictionary carries (the line directory). The page
 * only hides the buttons; the server decides.
 */
import { useState } from 'react'
import { ChevronLeft, ChevronRight, Upload } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount, formatPhone } from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { EnumFilter, SearchFilter, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { ContactDetailModal } from './ContactDetailModal'
import { ContactsImportModal } from './ContactsImportModal'
import {
  KINDS,
  KIND_HINT,
  KIND_LABEL,
  PAGE_SIZE,
  useContacts,
  useContactsSummary,
  useUpdateContact,
  type ContactKind,
  type ContactListQuery,
  type ContactPage,
} from './api'

function StatCard({
  label,
  value,
  active,
  onClick,
}: {
  label: string
  value: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={cn(
        'flex w-full flex-col items-start gap-0.5 rounded-xl border border-border',
        'bg-surface p-4 text-start shadow-soft transition-colors',
        'hover:border-accent/40 focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-accent/20',
        active && 'ring-1 ring-accent/40',
      )}
      aria-pressed={active}
      onClick={onClick}
    >
      <span className="text-2xs font-medium uppercase tracking-wide text-muted">
        {label}
      </span>
      <span className="text-lg font-semibold tabular-nums text-text">
        {formatCount(value)}
      </span>
    </button>
  )
}

function ContactRows({
  page,
  canWrite,
  onOpen,
  onKind,
}: {
  page: ContactPage
  canWrite: boolean
  onOpen: (phoneKey: string) => void
  onKind: (phoneKey: string, kind: ContactKind) => void
}) {
  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            <TH>{t('contacts.col.name')}</TH>
            <TH>{t('contacts.col.code')}</TH>
            <TH>{t('contacts.col.phone')}</TH>
            <TH>{t('contacts.col.kind')}</TH>
            <TH>{t('contacts.col.source')}</TH>
          </tr>
        </THead>
        <TBody>
          {page.items.map((row) => (
            <TR
              key={row.phone_key}
              interactive
              // A `<tr>` is not natively focusable, so without these the card
              // could only be opened with a mouse.
              tabIndex={0}
              role="button"
              onClick={() => onOpen(row.phone_key)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onOpen(row.phone_key)
                }
              }}
            >
              <TD className="max-w-[18rem]">
                <span className="block truncate font-medium">
                  {row.name ?? row.raw_name}
                </span>
                {/* The handset's own wording, shown only when the code was cut
                    out of it — so "why is this name different?" is answerable
                    from the row rather than by reopening the file. */}
                {row.name && row.name !== row.raw_name ? (
                  <span className="block truncate text-2xs text-muted">
                    {row.raw_name}
                  </span>
                ) : null}
              </TD>
              <TD className="whitespace-nowrap">
                {row.code ? (
                  <span className="font-mono text-accent">{row.code}</span>
                ) : (
                  <span className="text-muted">{EM_DASH}</span>
                )}
                {/* ⚠️ Two numbers for one customer is the ORDINARY case, not an
                    error: the key is the number, so each takes its own row and
                    both lead to one code. Without this badge the row reads as
                    a duplicate. */}
                {row.code && row.code_numbers > 1 ? (
                  <span
                    title={t('contacts.multiNumberHint', { count: row.code_numbers })}
                  >
                    <Badge tone="accent" className="ms-1.5">
                      {t('contacts.multiNumber', { count: row.code_numbers })}
                    </Badge>
                  </span>
                ) : null}
              </TD>
              <TD className="whitespace-nowrap font-mono text-muted">
                {formatPhone(row.phone) ?? row.phone_key}
              </TD>
              <TD onClick={(event) => event.stopPropagation()}>
                {canWrite ? (
                  <select
                    className={cn(SELECT_CLASS, 'w-full')}
                    // Names the CONTACT, not just the column: a screen reader
                    // meeting fifty selects all called "Turi" cannot tell
                    // which row it is on, and the filter above is called that
                    // too.
                    aria-label={t('contacts.kindOf', { name: row.raw_name })}
                    value={row.kind}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) =>
                      onKind(row.phone_key, event.target.value as ContactKind)
                    }
                  >
                    {KINDS.map((kind) => (
                      <option key={kind} value={kind}>
                        {t(KIND_LABEL[kind])}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="text-muted" title={t(KIND_HINT[row.kind])}>
                    {t(KIND_LABEL[row.kind])}
                  </span>
                )}
              </TD>
              <TD className="max-w-[12rem] truncate text-2xs text-muted">
                {row.source_file ?? EM_DASH}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  )
}

export function ContactsPage() {
  const can = useAuth((state) => state.can)
  const canWrite = can(Perm.SETTINGS_WRITE)

  const [search, setSearch] = useState<string | undefined>(undefined)
  const [kind, setKind] = useState<ContactKind | undefined>(undefined)
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [trail, setTrail] = useState<string[]>([])
  const [importing, setImporting] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)

  const query: ContactListQuery = {
    limit: PAGE_SIZE,
    ...(search ? { search } : {}),
    ...(kind ? { kind } : {}),
    ...(cursor ? { cursor } : {}),
    with_total: cursor === undefined,
  }
  const contactsQuery = useContacts(query)
  const summaryQuery = useContactsSummary()
  const updateKind = useUpdateContact()
  const filtered = Boolean(search || kind)

  /** Any filter change invalidates every cursor taken under the old one. */
  function refilter(next: () => void) {
    setCursor(undefined)
    setTrail([])
    next()
  }

  const summary = summaryQuery.data

  return (
    <Page>
      <PageHeader
        title={t('page.contacts')}
        description={t('contacts.subtitle')}
        actions={
          canWrite ? (
            <Button variant="secondary" size="sm" onClick={() => setImporting(true)}>
              <Upload className="size-4" aria-hidden />
              {t('contacts.import.button')}
            </Button>
          ) : null
        }
      />

      {/* The cards are the filter: a count nobody can act on is decoration.
          Clicking one narrows the list to that kind and clicking the total
          clears it. */}
      {summary ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label={t('contacts.stat.total')}
            value={summary.total}
            active={kind === undefined}
            onClick={() => refilter(() => setKind(undefined))}
          />
          {(['client', 'unknown', 'personal'] as const).map((value) => (
            <StatCard
              key={value}
              label={t(KIND_LABEL[value])}
              value={summary.by_kind[value] ?? 0}
              active={kind === value}
              onClick={() => refilter(() => setKind(value))}
            />
          ))}
        </div>
      ) : null}

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <SearchFilter
          label={t('contacts.searchLabel')}
          placeholder={t('contacts.searchPlaceholder')}
          clearLabel={t('contacts.searchClear')}
          value={search}
          onCommit={(value) => refilter(() => setSearch(value ?? undefined))}
          className="min-w-[16rem] flex-1 sm:max-w-md"
        />
        <EnumFilter
          label={t('contacts.filterKind')}
          allLabel={t('contacts.filter.allKinds')}
          labels={KIND_LABEL}
          value={kind}
          onChange={(value) =>
            refilter(() => setKind((value ?? undefined) as ContactKind | undefined))
          }
        />
        <span className="ms-auto whitespace-nowrap text-xs text-muted">
          {typeof contactsQuery.data?.total === 'number'
            ? t('contacts.found', { count: formatCount(contactsQuery.data.total) })
            : EM_DASH}
        </span>
      </Card>

      <QueryBoundary
        query={contactsQuery}
        isEmpty={(page) => page.items.length === 0}
        emptyTitle={filtered ? t('contacts.emptyFiltered') : t('contacts.empty')}
        emptyHint={filtered ? undefined : t('contacts.emptyHint')}
        emptyAction={
          !filtered && canWrite ? (
            <Button variant="secondary" size="sm" onClick={() => setImporting(true)}>
              <Upload className="size-4" aria-hidden />
              {t('contacts.import.button')}
            </Button>
          ) : undefined
        }
        skeletonRows={8}
      >
        {(page) => (
          <>
            <ContactRows
              page={page}
              canWrite={canWrite}
              onOpen={setPicked}
              onKind={(phoneKey, value) =>
                updateKind.mutate({ phoneKey, kind: value })
              }
            />
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {t('contacts.shown', { count: formatCount(page.items.length) })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={trail.length === 0}
                  onClick={() => {
                    const nextTrail = trail.slice(0, -1)
                    setTrail(nextTrail)
                    setCursor(nextTrail.at(-1))
                  }}
                >
                  <ChevronLeft className="size-4" aria-hidden />
                  {t('contacts.prevPage')}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!page.has_more || !page.next_cursor}
                  onClick={() => {
                    if (!page.next_cursor) return
                    setTrail([...trail, page.next_cursor])
                    setCursor(page.next_cursor)
                  }}
                >
                  {t('contacts.nextPage')}
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </>
        )}
      </QueryBoundary>

      {canWrite ? (
        <ContactsImportModal open={importing} onOpenChange={setImporting} />
      ) : null}
      <ContactDetailModal
        phoneKey={picked}
        onClose={() => setPicked(null)}
        canWrite={canWrite}
      />
    </Page>
  )
}
