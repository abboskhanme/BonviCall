/**
 * `/clients` — the customer directory.
 *
 * Ported from BonviZvonki `web/src/modules/clients/ClientsPage.tsx`.
 *
 * A customer here is ONE PHONE NUMBER and every conversation held with it —
 * not a row in a catalogue, because there is no customer catalogue and theirs
 * is empty. The server does the grouping on `calls.remote_number_key`; the
 * reasoning is in `server/src/modules/clients/rules.py`.
 *
 * Scope: a `sales` user reaches this page through `calls:read:own` and the
 * SERVER narrows the rows to the customers they have spoken to. The page does
 * not re-implement that rule — it only hides the agent filter, which is
 * presentation, not access control (CONVENTIONS-CLIENT.md §2).
 *
 * Loading, empty and error are `QueryBoundary`'s, not this page's.
 */
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowDown,
  ArrowDownLeft,
  ArrowUp,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  FilterX,
} from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t, type MessageKey } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import {
  EM_DASH,
  formatCount,
  formatDate,
  formatDuration,
  formatInstantTitle,
  formatPhone,
  formatTime,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import {
  DateFilter,
  EnumFilter,
  FilterField,
  SearchFilter,
  SELECT_CLASS,
} from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  FIRST_ORDER,
  PAGE_SIZE,
  useClients,
  type ClientListQuery,
  type ClientPage,
  type ClientRow,
  type ClientScope,
  type ClientSort,
} from './api'

/**
 * The URL is the screen state (CONVENTIONS-CLIENT.md §2) and the parameter
 * names are the server's own, so a filtered list is a link somebody can paste
 * into a chat and a colleague opens the same page.
 */
const PARAM_SEARCH = 'search'
const PARAM_SCOPE = 'scope'
const PARAM_AGENT = 'agent_id'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'
const PARAM_SORT = 'sort'
const PARAM_ORDER = 'order'
const PARAM_CURSOR = 'cursor'

/** Every filter, so "clear" and "is anything filtered" cannot miss one. */
const FILTER_PARAMS = [
  PARAM_SEARCH,
  PARAM_SCOPE,
  PARAM_AGENT,
  PARAM_DATE_FROM,
  PARAM_DATE_TO,
] as const

/**
 * The cut, and it is a view of the LIST rather than a truth about a customer.
 * `clients` is the default: everything except internal lines. `unknown` rows
 * are in it deliberately — not yet classified is not the same as not a
 * customer (`server/src/modules/clients/rules.py`).
 */
const SCOPE_LABEL: Record<ClientScope, MessageKey> = {
  clients: 'clients.scope.clients',
  internal: 'clients.scope.internal',
  all: 'clients.scope.all',
}

const SORT_VALUES: readonly ClientSort[] = [
  'last_call',
  'calls',
  'missed',
  'talk',
  'score',
  'name',
]

/**
 * The score colour bands, ported unchanged.
 *
 * Five bands rather than a gradient: a reader is deciding whether to listen to
 * the call, and "good / fine / watch / bad" is the whole of that decision.
 */
function scoreTone(score: number): string {
  if (score >= 85) return 'text-good'
  if (score >= 70) return 'text-accent'
  if (score >= 55) return 'text-warn'
  return 'text-bad'
}

function parseEnum<T extends string>(
  raw: string | null,
  allowed: readonly T[],
): T | undefined {
  return raw !== null && (allowed as readonly string[]).includes(raw)
    ? (raw as T)
    : undefined
}

/**
 * A sortable column header.
 *
 * Each column opens in the direction a reader means by clicking it —
 * "most recent first", "most calls first", but a name A→Z (`FIRST_ORDER`). A
 * table that opens every column descending puts the alphabet backwards.
 */
function SortHeader({
  field,
  labelKey,
  titleKey,
  align = 'start',
  sort,
  order,
  onSort,
}: {
  field: ClientSort
  labelKey: MessageKey
  titleKey?: MessageKey
  align?: 'start' | 'end'
  sort: ClientSort
  order: 'asc' | 'desc'
  onSort: (field: ClientSort, order: 'asc' | 'desc') => void
}) {
  const active = sort === field
  const Icon = !active ? ChevronsUpDown : order === 'asc' ? ArrowUp : ArrowDown
  return (
    <TH
      className={align === 'end' ? 'text-end' : undefined}
      aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
      title={titleKey ? t(titleKey) : undefined}
    >
      <button
        type="button"
        className={cn(
          'group inline-flex items-center gap-1 uppercase tracking-wide',
          'transition-colors hover:text-text',
          align === 'end' && 'flex-row-reverse',
          active && 'text-text',
        )}
        onClick={() =>
          onSort(field, active ? (order === 'asc' ? 'desc' : 'asc') : FIRST_ORDER[field])
        }
      >
        {t(labelKey)}
        <Icon
          className={cn(
            'size-3 shrink-0',
            !active && 'opacity-0 transition-opacity group-hover:opacity-40',
          )}
          aria-hidden
        />
      </button>
    </TH>
  )
}

function ClientRows({
  page,
  showAgent,
  scope,
  sort,
  order,
  onSort,
}: {
  page: ClientPage
  showAgent: boolean
  scope: ClientScope | undefined
  sort: ClientSort
  order: 'asc' | 'desc'
  onSort: (field: ClientSort, order: 'asc' | 'desc') => void
}) {
  const navigate = useNavigate()
  // ⚠️ The cut travels with the link. The server defaults to `clients`, so an
  // internal number opened without it would be found only by the card's own
  // widening rule — which works, but then the card and the list disagree about
  // which cut the reader is in.
  const href = (row: ClientRow) =>
    scope && scope !== 'clients'
      ? `/clients/${row.phone_key}?${PARAM_SCOPE}=${scope}`
      : `/clients/${row.phone_key}`

  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            <SortHeader
              field="name"
              labelKey="clients.colClient"
              sort={sort}
              order={order}
              onSort={onSort}
            />
            <SortHeader
              field="calls"
              labelKey="clients.colCalls"
              align="end"
              sort={sort}
              order={order}
              onSort={onSort}
            />
            {/* Not sortable, and deliberately one column: the two numbers are
                read against each other, and sorting by half of a ratio is a
                question nobody asks. */}
            <TH className="text-end" title={t('clients.colInOutHint')}>
              {t('clients.colInOut')}
            </TH>
            {/* ⚠️ "Ko'tarmadi" is INCOMING and unanswered — the company's
                failure. An unanswered OUTGOING call is the customer being
                busy, and it is NOT added here: measured over a week, 983
                against 1047, so combining them doubles the figure and blames
                the employee for it. */}
            <SortHeader
              field="missed"
              labelKey="clients.colMissedShort"
              titleKey="clients.colMissed"
              align="end"
              sort={sort}
              order={order}
              onSort={onSort}
            />
            <SortHeader
              field="talk"
              labelKey="clients.colTalk"
              align="end"
              sort={sort}
              order={order}
              onSort={onSort}
            />
            <SortHeader
              field="score"
              labelKey="clients.colScoreShort"
              titleKey="clients.colScore"
              align="end"
              sort={sort}
              order={order}
              onSort={onSort}
            />
            <SortHeader
              field="last_call"
              labelKey="clients.colLastCallShort"
              titleKey="clients.colLastCall"
              align="end"
              sort={sort}
              order={order}
              onSort={onSort}
            />
            {showAgent ? <TH>{t('clients.colAgent')}</TH> : null}
          </tr>
        </THead>
        <TBody>
          {page.items.map((row) => (
            <TR key={row.phone_key} interactive onClick={() => navigate(href(row))}>
              <TD className="max-w-[18rem]">
                {/* The keyboard path into the card. A bare onClick on the row
                    is unreachable without a mouse. */}
                <Link
                  to={href(row)}
                  className="block truncate font-medium text-text hover:text-accent"
                  onClick={(event) => event.stopPropagation()}
                >
                  {row.name ?? (
                    <span className="text-muted">{t('clients.noName')}</span>
                  )}
                </Link>
                <span className="mt-0.5 flex items-center gap-1.5 text-2xs text-muted">
                  {/* The customer code, where the uploaded phonebook carried
                      one. It is what ties this conversation to an accounting
                      record, so it sits under the name rather than behind a
                      hover. */}
                  {row.code ? (
                    <span className="font-mono text-accent">{row.code}</span>
                  ) : null}
                  <span className="font-mono">
                    {formatPhone(row.phone) ?? row.phone_key}
                  </span>
                </span>
              </TD>
              <TD className="text-end font-mono tabular-nums">
                {formatCount(row.calls_total)}
              </TD>
              <TD className="whitespace-nowrap text-end font-mono tabular-nums text-muted">
                <span title={t('clients.inboundHint')}>
                  <ArrowDownLeft className="inline size-3 shrink-0" aria-hidden />{' '}
                  {formatCount(row.inbound)}
                </span>
                <span className="mx-1.5" aria-hidden>
                  ·
                </span>
                <span title={t('clients.outboundHint')}>
                  <ArrowUpRight className="inline size-3 shrink-0" aria-hidden />{' '}
                  {formatCount(row.outbound)}
                </span>
              </TD>
              <TD
                className={cn(
                  'text-end font-mono tabular-nums',
                  row.missed > 0 ? 'font-medium text-bad' : 'text-muted',
                )}
              >
                {formatCount(row.missed)}
              </TD>
              <TD className="text-end font-mono tabular-nums">
                {formatDuration(row.talk_seconds)}
              </TD>
              {/* ⚠️ An unscored customer shows a dash and NOTHING else. A zero
                  or an empty bar reads as "scored nought", and unscored rows
                  are common enough to fill the whole column with that lie. */}
              <TD
                className={cn(
                  'text-end font-mono tabular-nums',
                  row.avg_score === null
                    ? 'text-muted'
                    : cn('font-medium', scoreTone(row.avg_score)),
                )}
                title={
                  row.avg_score === null
                    ? undefined
                    : t('clients.scoredOf', { total: row.calls_total, scored: row.scored })
                }
              >
                {row.avg_score === null ? EM_DASH : Math.round(row.avg_score)}
              </TD>
              <TD className="whitespace-nowrap text-end">
                {row.last_call_at === null ? (
                  <span className="text-muted">{EM_DASH}</span>
                ) : (
                  <span title={formatInstantTitle(row.last_call_at)}>
                    {formatDate(row.last_call_at)}
                    <span className="block text-2xs text-muted">
                      {formatTime(row.last_call_at)}
                    </span>
                  </span>
                )}
              </TD>
              {showAgent ? (
                <TD className="max-w-[12rem]">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate">
                      {row.main_agent_name ?? (
                        <span className="text-muted">{EM_DASH}</span>
                      )}
                    </span>
                    {/* One customer, several employees — a handover, a holiday,
                        a change of job. The badge is what makes that visible
                        without a second column. */}
                    {row.agent_count > 1 ? (
                      <Badge>+{row.agent_count - 1}</Badge>
                    ) : null}
                  </span>
                </TD>
              ) : null}
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  )
}

export function ClientsPage() {
  const can = useAuth((state) => state.can)
  // Full `calls:read` sees everybody; `calls:read:own` sees one agent's
  // customers, so the column would be one repeated name.
  const showAgent = can(Perm.CALLS_READ)

  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.get(PARAM_SEARCH) ?? undefined
  const scope = parseEnum<ClientScope>(searchParams.get(PARAM_SCOPE), [
    'clients',
    'internal',
    'all',
  ])
  const agentId = searchParams.get(PARAM_AGENT) ?? undefined
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const sort = parseEnum<ClientSort>(searchParams.get(PARAM_SORT), SORT_VALUES) ?? 'last_call'
  const order = searchParams.get(PARAM_ORDER) === 'asc' ? 'asc' : 'desc'
  const cursor = searchParams.get(PARAM_CURSOR) ?? undefined

  /**
   * The trail of cursors already visited, so "previous" works.
   *
   * A keyset cursor points into a moving stream and only ever goes forward, so
   * there is no page number to put in the URL. The current page IS in the URL,
   * which is what makes a row linkable; the trail is component state, and a
   * pasted deep link starts a fresh one.
   */
  const [trail, setTrail] = useState<string[]>([])

  const query: ClientListQuery = {
    limit: PAGE_SIZE,
    sort,
    order,
    ...(cursor ? { cursor } : {}),
    ...(search ? { search } : {}),
    ...(scope ? { scope } : {}),
    ...(agentId ? { agent_id: [agentId] } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    // A COUNT over a grouped aggregate is affordable once per filter change
    // and not once per page — the rule `/calls` already follows.
    with_total: cursor === undefined,
  }

  const clientsQuery = useClients(query)
  const agentsQuery = useAgentDirectory(showAgent && can(Perm.AGENTS_READ))
  const filtered = FILTER_PARAMS.some((param) => searchParams.get(param) !== null)

  /**
   * The last total the server gave, and which filter it was the total OF.
   *
   * Only the first page asks for a count, so every page after it answers null
   * and the header would turn "742 ta mijoz" into a dash on page two — which
   * reads as a number that got lost. Holding it across a FILTER change would
   * be a lie, so the filter it belongs to is compared.
   */
  const filterKey = FILTER_PARAMS.map((param) => searchParams.get(param) ?? '').join(' ')
  const [heldTotal, setHeldTotal] = useState<{ key: string; total: number } | null>(null)
  const pageTotal = clientsQuery.data?.total
  if (typeof pageTotal === 'number' && heldTotal?.total !== pageTotal) {
    // Derived during render rather than in an effect: it is a value, not a
    // side effect, and an effect would paint the dash for one frame first.
    setHeldTotal({ key: filterKey, total: pageTotal })
  }
  const total =
    typeof pageTotal === 'number'
      ? pageTotal
      : heldTotal?.key === filterKey
        ? heldTotal.total
        : undefined

  function applyFilters(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    // Any filter or sort change invalidates every cursor taken under the old
    // one. Without this, somebody on page five who narrows a filter is served
    // an empty table and reads it as "no data".
    next.delete(PARAM_CURSOR)
    setTrail([])
    setSearchParams(next, { replace: true })
  }

  function goToCursor(nextCursor: string | null, nextTrail: string[]) {
    const next = new URLSearchParams(searchParams)
    if (nextCursor === null) next.delete(PARAM_CURSOR)
    else next.set(PARAM_CURSOR, nextCursor)
    setTrail(nextTrail)
    setSearchParams(next)
  }

  return (
    <Page>
      <PageHeader
        title={t('page.clients')}
        description={showAgent ? t('clients.subtitle') : t('clients.ownScopeNote')}
      />

      <Card className="flex flex-col gap-3 p-3">
        <div className="flex flex-wrap items-center gap-3">
          <SearchFilter
            label={t('clients.searchLabel')}
            placeholder={t('clients.searchPlaceholder')}
            clearLabel={t('clients.searchClear')}
            value={search}
            onCommit={(value) => applyFilters({ [PARAM_SEARCH]: value })}
            className="min-w-[16rem] flex-1 sm:max-w-md"
          />
          <span className="ms-auto whitespace-nowrap text-xs text-muted">
            {typeof total === 'number'
              ? t('clients.found', { count: formatCount(total) })
              : EM_DASH}
          </span>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
          {showAgent ? (
            <FilterField label={t('clients.filterAgent')}>
              <select
                className={SELECT_CLASS}
                value={agentId ?? ''}
                onChange={(event) =>
                  applyFilters({ [PARAM_AGENT]: event.target.value || null })
                }
              >
                <option value="">{t('clients.filterAgentAll')}</option>
                {(agentsQuery.data?.items ?? []).map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.full_name}
                  </option>
                ))}
              </select>
            </FilterField>
          ) : null}

          <EnumFilter
            label={t('clients.filterScope')}
            allLabel={t('clients.scope.clients')}
            labels={SCOPE_LABEL}
            value={scope}
            onChange={(value) => applyFilters({ [PARAM_SCOPE]: value })}
          />

          {/* Asia/Tashkent calendar dates, inclusive on both ends. BOTH may be
              left empty and that is the default: the directory's first
              question is "who are our customers", and a window that silently
              defaulted to the last week would answer a different one. */}
          <DateFilter
            label={t('clients.filterDateFrom')}
            hint={t('clients.filterDateEmpty')}
            pickLabel={t('clients.filterDatePickFrom')}
            clearLabel={t('clients.filterDateClearFrom')}
            value={dateFrom}
            max={dateTo}
            onChange={(value) => applyFilters({ [PARAM_DATE_FROM]: value })}
          />
          <DateFilter
            label={t('clients.filterDateTo')}
            hint={t('clients.filterDateEmpty')}
            pickLabel={t('clients.filterDatePickTo')}
            clearLabel={t('clients.filterDateClearTo')}
            value={dateTo}
            min={dateFrom}
            onChange={(value) => applyFilters({ [PARAM_DATE_TO]: value })}
          />

          {filtered ? (
            <Button
              variant="ghost"
              size="sm"
              className="ms-auto"
              onClick={() => {
                const next = new URLSearchParams(searchParams)
                for (const param of FILTER_PARAMS) next.delete(param)
                next.delete(PARAM_CURSOR)
                setTrail([])
                setSearchParams(next, { replace: true })
              }}
            >
              <FilterX className="size-4" aria-hidden />
              {t('clients.filterReset')}
            </Button>
          ) : null}
        </div>
      </Card>

      <QueryBoundary
        query={clientsQuery}
        isEmpty={(page) => page.items.length === 0}
        // "No customers yet" and "nothing matches this filter" are different
        // sentences and must stay different (SPEC §5.3).
        emptyTitle={filtered ? t('clients.emptyFiltered') : t('clients.emptyAll')}
        emptyHint={filtered ? t('clients.emptyFilteredHint') : t('clients.emptyAllHint')}
        skeletonRows={8}
      >
        {(page) => (
          <>
            <ClientRows
              page={page}
              showAgent={showAgent}
              scope={scope}
              sort={sort}
              order={order}
              onSort={(field, nextOrder) =>
                applyFilters({ [PARAM_SORT]: field, [PARAM_ORDER]: nextOrder })
              }
            />

            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {t('clients.shown', { count: formatCount(page.items.length) })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={trail.length === 0}
                  onClick={() => {
                    const nextTrail = trail.slice(0, -1)
                    goToCursor(nextTrail.at(-1) ?? null, nextTrail)
                  }}
                >
                  <ChevronLeft className="size-4" aria-hidden />
                  {t('clients.prevPage')}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!page.has_more || !page.next_cursor}
                  onClick={() => {
                    if (!page.next_cursor) return
                    goToCursor(page.next_cursor, [...trail, page.next_cursor])
                  }}
                >
                  {t('clients.nextPage')}
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </>
        )}
      </QueryBoundary>
    </Page>
  )
}
