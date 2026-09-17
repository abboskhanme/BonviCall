/**
 * `/sales` — sales control.
 *
 * Ported from BonviZvonki `web/src/modules/sales/SalesControlPage.tsx`.
 *
 * THE QUESTION: was the sale agreed through a recorded conversation, or
 * outside the system? The signal is simple — SAP has a sale and we have no
 * matching conversation.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ THIS LIST DOES NOT ACCUSE. It prepares a queue to be checked; the
 * judgement is the manager's. Hence:
 *   · a suspicious sale is AMBER, not red — red appears only after a person
 *     has decided "really suspicious";
 *   · all three classes stay on screen, including "could not be checked",
 *     which measures SAP's data quality and does NOT mean "clean";
 *   · every row carries EVIDENCE — date, customer code, phone and the last
 *     conversation — because the manager re-derives the number by hand.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ⚠️ EVIDENCE IS NEVER WRITTEN INTO A CELL AS A SENTENCE. The source tried it:
 * "Oldingi savdo 19/08/2026 — orasida 0 ta suhbat" wrapped to four lines in a
 * narrow column and made that row three times its neighbours' height. The
 * split is now: TABLE — status codes only, every cell one height; MEANING —
 * one legend line under the header, once for every row; DETAIL — the card that
 * opens when a row is clicked.
 *
 * ⚠️ TWO SECTIONS AND AN INDEPENDENT AXIS, which is NOT how the source drew
 * it. There, "out of scope" was a third tab that dropped `client_kind`
 * entirely — so a walk-in sale belonging to an excluded customer appeared in
 * no section at all (the server measured 47 of them). Here `client_kind` and
 * `out_of_scope` are what they are on the wire: two independent filters. Two
 * tabs, one switch, four combinations, and every sale is in exactly one of
 * them.
 *
 * Scope: `reports:read` opens the page. The `sales` ROLE holds none of this
 * module's permissions and gets 403 on all ten routes — a check carried out ON
 * salespeople is not a page they open.
 *
 * Loading, empty and error are `QueryBoundary`'s, not this page's.
 */
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FilterX,
  Send,
  ShieldCheck,
  Store,
  TriangleAlert,
  Upload,
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
  formatDateTime,
  formatInstantTitle,
  formatPhone,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { DateFilter, EnumFilter, FilterField, SearchFilter, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  KIND_LABEL,
  PAGE_SIZE,
  REVIEW_LABEL,
  RULES,
  RULE_LABEL,
  VERDICTS,
  VERDICT_HINT,
  VERDICT_LABEL,
  useCompliance,
  useComplianceSummary,
  useSaleBranches,
  type ClientKind,
  type ComplianceItem,
  type ComplianceList,
  type ComplianceQuery,
  type ComplianceScope,
  type ComplianceSummary,
  type ReviewState,
  type Rule,
  type Verdict,
} from './api'
import { ReviewBadge, RuleBadges, RuleLegend, SkipBadge, VerdictBadge } from './badges'
import { BranchesModal } from './BranchesModal'
import { DigestModal } from './DigestModal'
import { ImportModal } from './ImportModal'
import { ReviewModal } from './ReviewModal'
import { SaleCardModal } from './SaleCardModal'
import { formatSaleDate, formatUsd } from './saleDate'
import { sellerHint, sellerName, sellerUnlinked } from './seller'

/**
 * The URL is the screen state (CONVENTIONS-CLIENT.md §2), and the parameter
 * names are the server's own — so a filtered queue is a link somebody can
 * paste into a chat and a colleague opens exactly the same page.
 *
 * The source kept the section in the PATH (`/sales`, `/sales/walk-in`,
 * `/sales/excluded`) to get two menu entries out of it. Here it is a search
 * parameter: this panel's convention is that screen state lives in the query
 * string, the back button works either way, and three route-table lines for
 * one page is three chances for the table and the page to disagree.
 */
const PARAM_KIND = 'client_kind'
const PARAM_OUT_OF_SCOPE = 'out_of_scope'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'
const PARAM_AGENT = 'agent_id'
const PARAM_BRANCH = 'branch'
const PARAM_SEARCH = 'search'
const PARAM_VERDICT = 'verdict'
const PARAM_RULE = 'rule'
const PARAM_REVIEW = 'review'
const PARAM_OVER_LIMIT = 'over_limit'
const PARAM_ORDER = 'order'
const PARAM_CURSOR = 'cursor'

/**
 * The filters "clear" resets and "is anything filtered" asks about.
 *
 * The section itself is NOT among them: switching to walk-ins and pressing
 * "clear filters" must not throw the reader back to regular customers.
 */
const FILTER_PARAMS = [
  PARAM_DATE_FROM,
  PARAM_DATE_TO,
  PARAM_AGENT,
  PARAM_BRANCH,
  PARAM_SEARCH,
  PARAM_VERDICT,
  PARAM_RULE,
  PARAM_REVIEW,
  PARAM_OVER_LIMIT,
] as const

const KINDS: readonly ClientKind[] = ['regular', 'walk_in']
const REVIEW_VALUES: readonly ReviewState[] = ['new', 'justified', 'confirmed', 'all']

/** The rule filter's options, labelled by the code the table also prints. */
const RULE_FILTER_LABEL: Record<Rule, MessageKey> = RULE_LABEL

function parseEnum<T extends string>(raw: string | null, allowed: readonly T[]): T | undefined {
  return raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : undefined
}

/**
 * One class of verdict, as a card that is also a filter.
 *
 * ⚠️ The long explanation stays in the HOVER. On the card it was two lines,
 * and the three of them together ate a third of the screen before a single
 * sale was visible.
 */
function VerdictTile({
  verdict,
  value,
  active,
  onClick,
}: {
  verdict: Verdict
  value: number
  active: boolean
  onClick: () => void
}) {
  const TONE: Record<Verdict, { text: string; tile: string; ring: string }> = {
    ok: { text: 'text-good', tile: 'bg-good/10 text-good', ring: 'ring-good/40' },
    suspicious: { text: 'text-warn', tile: 'bg-warn/10 text-warn', ring: 'ring-warn/40' },
    not_checkable: { text: 'text-muted', tile: 'bg-surface-2 text-muted', ring: 'ring-border' },
  }
  const ICON: Record<Verdict, typeof ShieldCheck> = {
    ok: ShieldCheck,
    suspicious: TriangleAlert,
    not_checkable: CircleHelp,
  }
  const look = TONE[verdict]
  const Icon = ICON[verdict]

  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      title={t(VERDICT_HINT[verdict])}
      className={cn(
        'flex items-center gap-3 rounded-xl border border-border bg-surface p-3.5',
        'text-start shadow-soft transition-colors hover:bg-surface-2',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        active && `ring-2 ring-inset ${look.ring}`,
      )}
    >
      <span className={cn('grid size-9 shrink-0 place-items-center rounded-md', look.tile)}>
        <Icon className="size-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn('block text-2xl font-semibold leading-none tabular-nums', look.text)}>
          {formatCount(value)}
        </span>
        <span className="mt-1 block truncate text-2xs text-muted">
          {t(VERDICT_LABEL[verdict])}
        </span>
      </span>
      {/* So the card reads as a FILTER rather than as a read-out. */}
      <Check
        className={cn('size-4 shrink-0 text-accent', active ? 'opacity-100' : 'opacity-0')}
        aria-hidden
      />
    </button>
  )
}

/**
 * A plain count in the walk-in section.
 *
 * ⚠️ DELIBERATELY NOT `VerdictTile`. That one is bound to a class and takes
 * its colour and its hover text from it; here there is no class, because the
 * question is different. Forcing both into one component would fill it with
 * "if this is a walk-in…" branches.
 */
function StatTile({
  label,
  hint,
  value,
  tone = 'muted',
  active = false,
  onClick,
}: {
  label: string
  hint?: string
  value: number
  tone?: 'muted' | 'warn'
  active?: boolean
  onClick?: () => void
}) {
  const body = (
    <span className="min-w-0">
      <span className="block truncate text-2xs font-medium text-muted">{label}</span>
      <span
        className={cn(
          'mt-0.5 block text-2xl font-semibold tabular-nums',
          tone === 'warn' ? 'text-warn' : 'text-text',
        )}
      >
        {formatCount(value)}
      </span>
    </span>
  )
  const look = cn(
    'flex items-center gap-3 rounded-xl border border-border bg-surface p-3.5 text-start shadow-soft',
    active && 'ring-2 ring-inset ring-warn/40',
  )

  // A block that cannot be pressed must not look like a button.
  return onClick ? (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      title={hint}
      className={cn(
        look,
        'transition-colors hover:bg-surface-2 focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-accent/40',
      )}
    >
      {body}
    </button>
  ) : (
    <div className={look} title={hint}>
      {body}
    </div>
  )
}

/** The evidence appended to a rule's hover text. */
function ruleHints(row: ComplianceItem): Partial<Record<Rule, string>> {
  const hints: Partial<Record<Rule, string>> = {}
  if (row.broken_rules.includes('R2')) {
    hints.R2 = row.previous_sale_on
      ? t('sales.betweenCalls', {
          date: formatSaleDate(row.previous_sale_on),
          count: row.calls_between,
        })
      : t('sales.noPreviousSale')
  }
  if (row.broken_rules.includes('R3')) {
    hints.R3 = t('sales.callsTotal', { count: row.calls_total })
  }
  return hints
}

/** The decision's full text — reason and note — as a hover. */
function reviewTitle(row: ComplianceItem): string | undefined {
  if (!row.review) return undefined
  return [
    t('sales.decision.by', {
      who: row.review.reviewed_by ?? EM_DASH,
      when: row.review.reviewed_at ? formatSaleDate(row.review.reviewed_at) : EM_DASH,
    }),
    row.review.note ? `«${row.review.note}»` : null,
  ]
    .filter(Boolean)
    .join('\n')
}

function SaleRows({
  page,
  walkIn,
  canOpenCall,
  order,
  onOrder,
  onPick,
}: {
  page: ComplianceList
  walkIn: boolean
  canOpenCall: boolean
  order: 'asc' | 'desc'
  onOrder: (next: 'asc' | 'desc') => void
  onPick: (row: ComplianceItem) => void
}) {
  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            {/* ⚠️ THE ONLY SORTABLE COLUMN, and that is the contract, not an
                omission. The list is cursor-paged on `(occurred_on, id)` and
                the server has no `sort` parameter: a sort a keyset cursor
                cannot express silently loses rows, and here a lost row is a
                sale nobody checked. */}
            <TH
              aria-sort={order === 'asc' ? 'ascending' : 'descending'}
              title={t('sales.col.dateHint')}
            >
              <button
                type="button"
                className="inline-flex items-center gap-1 uppercase tracking-wide transition-colors hover:text-text"
                onClick={() => onOrder(order === 'desc' ? 'asc' : 'desc')}
              >
                {t('sales.col.date')}
                <span aria-hidden>{order === 'desc' ? '↓' : '↑'}</span>
              </button>
            </TH>
            <TH>{t('sales.col.client')}</TH>
            <TH>{t('sales.col.branchAgent')}</TH>
            <TH className="text-end">{t('sales.col.amountUsd')}</TH>
            <TH>{t('sales.col.verdict')}</TH>
            <TH>{t('sales.col.lastCall')}</TH>
            <TH>{t('sales.col.decision')}</TH>
          </tr>
        </THead>
        <TBody>
          {page.items.map((row) => (
            <TR
              key={row.id}
              interactive
              tabIndex={0}
              onClick={() => onPick(row)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return
                event.preventDefault()
                onPick(row)
              }}
            >
              {/* The date, with no clock. Under it SAP's OPERATION number: the
                  manager finds the row in SAP by exactly that, and without it
                  the evidence cannot be checked at all. */}
              <TD className="whitespace-nowrap">
                <span className="block tabular-nums">{formatSaleDate(row.occurred_on)}</span>
                {/* The "№" is deliberate: without it the number reads as a
                    second date under the first. */}
                <span className="block text-2xs tabular-nums text-muted">
                  № {row.external_id}
                </span>
              </TD>

              {/* The customer: name, then code and phone. Both are EVIDENCE —
                  the code for SAP, the phone for the call history. */}
              <TD className="max-w-[16rem]">
                <span
                  className="block truncate font-medium"
                  title={row.partner_name ?? row.partner_code}
                >
                  {/* With no name the CODE becomes the heading: an em dash
                      gives nothing, a code still finds the row in SAP. */}
                  {row.partner_name || row.partner_code}
                </span>
                <span className="block truncate text-2xs tabular-nums text-muted">
                  {row.partner_code}
                  {row.phone ? ` · ${formatPhone(row.phone) ?? row.phone}` : ''}
                </span>
              </TD>

              {/* ⚠️ THE EMPLOYEE — ONE name. SAP's `Подразделение` IS the
                  employee; the reasoning is in `seller.ts`. */}
              <TD className="max-w-[12rem]">
                <span className="block truncate" title={sellerName(row) ?? undefined}>
                  {sellerName(row) ?? EM_DASH}
                </span>
                <span
                  className={cn(
                    'block truncate text-2xs',
                    sellerUnlinked(row) ? 'text-warn' : 'text-muted',
                  )}
                >
                  {[sellerHint(row), row.direction].filter(Boolean).join(' · ') || EM_DASH}
                </span>
              </TD>

              {/* Dollars are the primary figure — comparison is meaningful in
                  one currency only — and the document's own currency sits
                  under it ONLY when it differs: printing "340 $" twice is
                  noise. */}
              <TD className="whitespace-nowrap text-end">
                <span className="block font-semibold tabular-nums">
                  {formatUsd(row.amount_usd)}
                </span>
                {row.currency !== 'USD' && row.amount !== null && row.amount !== undefined ? (
                  <span className="block text-2xs tabular-nums text-muted">
                    {formatCount(Math.round(row.amount))} {row.currency}
                  </span>
                ) : null}
              </TD>

              {/* ⚠️ STATUS CODES ONLY, on one line. The explanation is in the
                  legend above and the full sentence is in the card. */}
              <TD>
                <span className="flex items-center gap-1.5 overflow-hidden">
                  <VerdictBadge verdict={row.verdict} skipReason={row.skip_reason} />
                  {row.skip_reason ? <SkipBadge reason={row.skip_reason} /> : null}
                  <RuleBadges
                    rules={row.broken_rules}
                    windowDays={page.window_days}
                    hints={ruleHints(row)}
                  />
                  {/* Only ever true in the walk-in section — a large sale to a
                      regular customer is an ordinary event. */}
                  {walkIn && row.over_limit ? (
                    <span className="inline-flex shrink-0">
                      <Badge tone="warn" className="whitespace-nowrap">
                        {t('sales.card.overLimit')}
                      </Badge>
                    </span>
                  ) : null}
                </span>
              </TD>

              {/* The most valuable column. "No conversation" is written out
                  rather than left blank — a blank cell reads as "failed to
                  load", which is the opposite conclusion. It is not a red
                  badge either: colour arrives only after a person decides. */}
              <TD className="max-w-[13rem]">
                {row.last_call_at ? (
                  <>
                    <span
                      className="block truncate tabular-nums"
                      title={formatInstantTitle(row.last_call_at)}
                    >
                      {/* ⚠️ NEW HERE: the conversation is a LINK. The source
                          printed a date and a name with nothing behind them,
                          so proving the row meant finding the call by hand.
                          Only rendered for a reader who can open a call —
                          otherwise the link would lead to a redirect. */}
                      {canOpenCall && row.last_call_id ? (
                        <Link
                          to={`/calls/${row.last_call_id}`}
                          className="text-accent hover:underline"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {formatDateTime(row.last_call_at)}
                        </Link>
                      ) : (
                        formatDateTime(row.last_call_at)
                      )}
                    </span>
                    <span className="block truncate text-2xs text-muted">
                      {row.last_call_agent ?? EM_DASH}
                      {row.days_before !== null && row.days_before !== undefined
                        ? ` · ${t('sales.daysBefore', { count: row.days_before })}`
                        : ''}
                    </span>
                  </>
                ) : (
                  <span className="text-xs text-muted">{t('sales.noCallPlain')}</span>
                )}
              </TD>

              {/* The decision, and under it WHO made it. The reason and the
                  note are in the hover and in the card: in the cell they ran
                  to three lines and stretched the row. */}
              <TD className="max-w-[11rem]">
                <ReviewBadge review={row.review} />
                {row.review ? (
                  <span className="mt-1 block truncate text-2xs text-muted" title={reviewTitle(row)}>
                    {t('sales.decision.by', {
                      who: row.review.reviewed_by ?? EM_DASH,
                      when: row.review.reviewed_at
                        ? formatSaleDate(row.review.reviewed_at)
                        : EM_DASH,
                    })}
                  </span>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  )
}

/** The counts above the table — a different question per section. */
function SummaryTiles({
  summary,
  walkIn,
  verdict,
  overLimit,
  onVerdict,
  onOverLimit,
}: {
  summary: ComplianceSummary
  walkIn: boolean
  verdict: Verdict | undefined
  overLimit: boolean
  onVerdict: (next: Verdict | null) => void
  onOverLimit: (next: boolean) => void
}) {
  if (walkIn) {
    /* ⚠️ A DIFFERENT QUESTION, SO DIFFERENT CARDS. The classes are meaningless
       here: the rules do not apply, so every sale would be "could not be
       checked" and two of the three boxes would read nought for ever. Under a
       shared code the only workable measure is the size of the ticket.
       `over_limit` and `walk_in_limit` are zero in the regular section, which
       is why they are drawn nowhere else. */
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <StatTile
          label={t('sales.kind.tiles.total')}
          hint={t('sales.kind.tiles.totalHint')}
          value={summary.total}
        />
        <StatTile
          label={t('sales.kind.tiles.overLimit', { limit: formatUsd(summary.walk_in_limit) })}
          hint={t('sales.kind.tiles.overLimitHint', {
            amount: formatUsd(summary.over_limit_amount),
          })}
          value={summary.over_limit}
          tone="warn"
          active={overLimit}
          onClick={() => onOverLimit(!overLimit)}
        />
      </div>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {VERDICTS.map((key) => (
        <VerdictTile
          key={key}
          verdict={key}
          value={summary[key]}
          active={verdict === key}
          onClick={() => onVerdict(verdict === key ? null : key)}
        />
      ))}
    </div>
  )
}

export function SalesPage() {
  const can = useAuth((state) => state.can)
  const canImport = can(Perm.SETTINGS_WRITE)
  const canReview = can(Perm.CALLS_NOTE)
  const canOpenCall = can(Perm.CALLS_READ) || can(Perm.CALLS_READ_OWN)

  const [searchParams, setSearchParams] = useSearchParams()

  const kind = parseEnum<ClientKind>(searchParams.get(PARAM_KIND), KINDS) ?? 'regular'
  const walkIn = kind === 'walk_in'
  const outOfScope = searchParams.get(PARAM_OUT_OF_SCOPE) === '1'
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const agentId = searchParams.get(PARAM_AGENT) ?? undefined
  const branch = searchParams.get(PARAM_BRANCH) ?? undefined
  const search = searchParams.get(PARAM_SEARCH) ?? undefined
  const verdict = parseEnum<Verdict>(searchParams.get(PARAM_VERDICT), VERDICTS)
  const rule = parseEnum<Rule>(searchParams.get(PARAM_RULE), RULES)
  const review = parseEnum<ReviewState>(searchParams.get(PARAM_REVIEW), REVIEW_VALUES) ?? 'new'
  const overLimit = searchParams.get(PARAM_OVER_LIMIT) === '1'
  const order = searchParams.get(PARAM_ORDER) === 'asc' ? 'asc' : 'desc'
  const cursor = searchParams.get(PARAM_CURSOR) ?? undefined

  const [trail, setTrail] = useState<string[]>([])
  const [tracked, setTracked] = useState<ComplianceItem | null>(null)
  const [picked, setPicked] = useState<ComplianceItem | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [branchesOpen, setBranchesOpen] = useState(false)
  const [digestOpen, setDigestOpen] = useState(false)

  /**
   * THE SCOPE — period and cut, and nothing that narrows the list.
   *
   * The three counts above the table are computed over exactly this. Its type
   * is the summary endpoint's own, so a filter that belongs to the list
   * cannot be added here by accident: it would not compile.
   */
  const scope: ComplianceScope = {
    client_kind: kind,
    out_of_scope: outOfScope,
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    // Repeated parameters on the wire; the pickers choose one each.
    ...(agentId ? { agent_id: [agentId] } : {}),
    ...(branch ? { branch: [branch] } : {}),
    ...(search ? { search } : {}),
  }

  const query: ComplianceQuery = {
    ...scope,
    limit: PAGE_SIZE,
    order,
    review,
    /* ⚠️ NO CLASS OR RULE FILTER IN THE WALK-IN SECTION. Every sale there is
       `not_checkable` — the rules do not apply — so "suspicious" would always
       return an empty list and the reader would read that as a fault. */
    ...(!walkIn && verdict ? { verdict } : {}),
    ...(!walkIn && rule ? { rule } : {}),
    ...(walkIn && overLimit ? { over_limit: true } : {}),
    ...(cursor ? { cursor } : {}),
    // A count over this aggregate is affordable once per filter change and not
    // once per page — the rule `/calls` and `/clients` already follow.
    with_total: cursor === undefined,
  }

  const listQuery = useCompliance(query)
  const summaryQuery = useComplianceSummary(scope)
  const agentsQuery = useAgentDirectory(can(Perm.AGENTS_READ))
  const branchesQuery = useSaleBranches()

  const windowDays = summaryQuery.data?.window_days ?? listQuery.data?.window_days
  const filtered = FILTER_PARAMS.some((param) => searchParams.get(param) !== null)

  /**
   * The last total the server gave, and which filter it was the total OF.
   *
   * Only the first page asks for a count, so every later page answers null and
   * the header would turn "451 ta savdo" into a dash on page two — which reads
   * as a number that got lost. Holding it across a FILTER change would be a
   * lie, so the filter it belongs to is compared.
   */
  const filterKey = [PARAM_KIND, PARAM_OUT_OF_SCOPE, ...FILTER_PARAMS]
    .map((param) => searchParams.get(param) ?? '')
    .join(' ')
  const [heldTotal, setHeldTotal] = useState<{ key: string; total: number } | null>(null)
  const pageTotal = listQuery.data?.total
  if (typeof pageTotal === 'number' && heldTotal?.total !== pageTotal) {
    setHeldTotal({ key: filterKey, total: pageTotal })
  }
  const total =
    typeof pageTotal === 'number'
      ? pageTotal
      : heldTotal?.key === filterKey
        ? heldTotal.total
        : undefined

  /**
   * Any change to a filter invalidates every cursor taken under the old one.
   *
   * Without this, somebody on page five who narrows a filter is served an
   * empty table and reads it as "no data".
   */
  function apply(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
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

  function switchKind(next: ClientKind) {
    if (next === kind) return
    // The list filters belonged to the other set, and so did the cursor. Left
    // in place they would land the reader on an empty page they would read as
    // a fault.
    apply({
      [PARAM_KIND]: next,
      [PARAM_VERDICT]: null,
      [PARAM_RULE]: null,
      [PARAM_OVER_LIMIT]: null,
    })
  }

  return (
    <Page>
      <PageHeader
        title={t('sales.title')}
        description={t('sales.subtitle')}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setBranchesOpen(true)}
              title={t('sales.branches.title')}
            >
              <Store className="size-4" aria-hidden />
              {t('sales.branches.button')}
            </Button>
            {canImport ? (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setDigestOpen(true)}
                  title={t('sales.digest.hint')}
                >
                  <Send className="size-4" aria-hidden />
                  {t('sales.digest.button')}
                </Button>
                <Button size="sm" onClick={() => setImportOpen(true)} title={t('sales.import.hint')}>
                  <Upload className="size-4" aria-hidden />
                  {t('sales.import.button')}
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      {/* ══════════════════════════════════════════════════════
          TWO SECTIONS, AND A SEPARATE SWITCH

          ⚠️ WHY THEY ARE SPLIT. A walk-in buyer is never written into the
          catalogue by name and number — they pass under one of a few SHARED
          codes. For such a sale the question "was this customer spoken to
          first?" is meaningless: one code, a hundred people. They used to sit
          in the same list and were counted as "could not be checked", which
          wrote a data-quality complaint into an employee's column when what it
          described was the KIND OF WORK.

          ⚠️ "Out of scope" is a SWITCH, not a third tab. It answers a
          different question — is this sale checked at all — and it applies
          within each section. As a third tab it dropped the section filter
          entirely, and a walk-in sale of an excluded customer then appeared in
          no list at all. ══════════════════════════════════════════════════ */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="tablist"
          aria-label={t('sales.kind.aria')}
          className="flex gap-1 rounded-md border border-border bg-surface p-0.5"
        >
          {KINDS.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={kind === value}
              onClick={() => switchKind(value)}
              className={cn(
                'rounded-sm px-3 py-1 text-xs font-medium transition-colors',
                kind === value ? 'bg-accent-soft text-accent' : 'text-muted hover:text-text',
              )}
            >
              {t(KIND_LABEL[value])}
            </button>
          ))}
        </div>

        <Button
          variant={outOfScope ? 'primary' : 'secondary'}
          size="sm"
          aria-pressed={outOfScope}
          title={t('sales.kind.excludedHint')}
          onClick={() => apply({ [PARAM_OUT_OF_SCOPE]: outOfScope ? null : '1' })}
        >
          {t('sales.kind.excluded')}
        </Button>
      </div>

      {/* ── The counts ────────────────────────────────────────
          ⚠️ NOT SHOWN OUT OF SCOPE, and deliberately. The cards answer "how is
          the checking going"; this section is precisely the sales that are NOT
          checked, so clean/suspicious counts beside them would contradict the
          section's own meaning. A sentence instead. */}
      {outOfScope ? (
        <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
          {t('sales.kind.excludedNote')}
        </p>
      ) : (
        <QueryBoundary query={summaryQuery} skeletonRows={1}>
          {(summary) => (
            <SummaryTiles
              summary={summary}
              walkIn={walkIn}
              verdict={verdict}
              overLimit={overLimit}
              onVerdict={(next) => apply({ [PARAM_VERDICT]: next })}
              onOverLimit={(next) => apply({ [PARAM_OVER_LIMIT]: next ? '1' : null })}
            />
          )}
        </QueryBoundary>
      )}

      {/* ── Filters ──────────────────────────────────────────── */}
      <Card className="flex flex-col gap-3 p-3">
        <div className="flex flex-wrap items-center gap-3">
          <SearchFilter
            label={t('sales.searchLabel')}
            placeholder={t('sales.searchPlaceholder')}
            clearLabel={t('sales.searchClear')}
            value={search}
            onCommit={(value) => apply({ [PARAM_SEARCH]: value })}
            className="min-w-[16rem] flex-1 sm:max-w-md"
          />
          <span className="ms-auto whitespace-nowrap text-xs text-muted">
            {typeof total === 'number' ? t('sales.found', { count: formatCount(total) }) : EM_DASH}
          </span>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
          {/* Asia/Tashkent calendar dates, inclusive at both ends, exactly as
              the calls list writes them — one control, one behaviour. */}
          <DateFilter
            label={t('calls.filterDateFrom')}
            hint={t('calls.filterDateEmpty')}
            pickLabel={t('calls.filterDatePickFrom')}
            clearLabel={t('calls.filterDateClearFrom')}
            value={dateFrom}
            max={dateTo}
            onChange={(value) => apply({ [PARAM_DATE_FROM]: value })}
          />
          <DateFilter
            label={t('calls.filterDateTo')}
            hint={t('calls.filterDateEmpty')}
            pickLabel={t('calls.filterDatePickTo')}
            clearLabel={t('calls.filterDateClearTo')}
            value={dateTo}
            min={dateFrom}
            onChange={(value) => apply({ [PARAM_DATE_TO]: value })}
          />

          {can(Perm.AGENTS_READ) ? (
            <FilterField label={t('sales.col.agent')}>
              <select
                className={SELECT_CLASS}
                value={agentId ?? ''}
                onChange={(event) => apply({ [PARAM_AGENT]: event.target.value || null })}
              >
                <option value="">{t('calls.filterAgentAll')}</option>
                {(agentsQuery.data?.items ?? []).map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.full_name}
                  </option>
                ))}
              </select>
            </FilterField>
          ) : null}

          <FilterField label={t('sales.branches.filter')}>
            <select
              className={SELECT_CLASS}
              value={branch ?? ''}
              onChange={(event) => apply({ [PARAM_BRANCH]: event.target.value || null })}
            >
              <option value="">{t('sales.branches.filterAll')}</option>
              {(branchesQuery.data?.items ?? []).map((row) => (
                <option key={row.branch} value={row.branch}>
                  {row.branch}
                </option>
              ))}
            </select>
          </FilterField>

          {/* ⚠️ Hidden among walk-ins: the rules do not apply there, so both
              pickers would only ever produce an empty list. */}
          {walkIn ? null : (
            <>
              <EnumFilter
                label={t('sales.col.verdict')}
                allLabel={t('sales.filter.anyVerdict')}
                labels={VERDICT_LABEL}
                value={verdict}
                onChange={(value) => apply({ [PARAM_VERDICT]: value })}
              />
              <EnumFilter
                label={t('sales.filter.rule')}
                allLabel={t('sales.filter.anyRule')}
                labels={RULE_FILTER_LABEL}
                value={rule}
                onChange={(value) => apply({ [PARAM_RULE]: value })}
              />
            </>
          )}

          {/* The decision filter. "Hammasi" sends an EXPLICIT `all`: omitting
              the parameter means "undecided" on the server, and the picker
              would then be lying about what is on screen. */}
          <FilterField label={t('sales.col.decision')}>
            <select
              className={SELECT_CLASS}
              value={review}
              onChange={(event) => apply({ [PARAM_REVIEW]: event.target.value })}
            >
              {REVIEW_VALUES.map((value) => (
                <option key={value} value={value}>
                  {t(REVIEW_LABEL[value])}
                </option>
              ))}
            </select>
          </FilterField>

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
              {t('sales.filter.reset')}
            </Button>
          ) : null}
        </div>

        {/* Said out loud: a sale has no clock, so the search window is the day
            of the sale plus the N days before it. Without this there is no
            answer to "but I spoke to them yesterday". */}
        {windowDays !== undefined ? (
          <p className="border-t border-border pt-2.5 text-2xs leading-relaxed text-muted">
            {t('sales.windowNote', { count: windowDays })}
          </p>
        ) : null}
      </Card>

      {/* What the codes mean — once, for every row. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <RuleLegend windowDays={windowDays} />
        <span className="ms-auto inline-flex items-center gap-1.5 text-2xs text-muted">
          <CircleHelp className="size-3.5" aria-hidden />
          {t('sales.rowHint')}
        </span>
      </div>

      <QueryBoundary
        query={listQuery}
        isEmpty={(page) => page.items.length === 0}
        // Three different sentences, because they call for three different
        // next actions (SPEC §5.3): widen the window, clear the search, or
        // stop — the queue is genuinely finished.
        emptyTitle={t('sales.emptyTitle')}
        emptyHint={
          search
            ? t('sales.emptySearchHint')
            : review === 'new'
              ? t('sales.emptyQueueHint')
              : t('sales.emptyHint')
        }
        skeletonRows={8}
      >
        {(page) => (
          <>
            <SaleRows
              page={page}
              walkIn={walkIn}
              canOpenCall={canOpenCall}
              order={order}
              onOrder={(next) => apply({ [PARAM_ORDER]: next })}
              onPick={setTracked}
            />

            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {t('sales.shown', { count: formatCount(page.items.length) })}
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
                  {t('sales.prevPage')}
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
                  {t('sales.nextPage')}
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </>
        )}
      </QueryBoundary>

      {/* Clicking a row opens the CARD first — "why is this suspicious" has to
          be answered before a decision, not after. The decision modal is
          reached from there, for whoever may record one. */}
      <SaleCardModal
        sale={tracked}
        windowDays={windowDays}
        walkInLimit={summaryQuery.data?.walk_in_limit}
        // The chain has to be asked in the SAME section the row came from: an
        // excluded customer's history is reachable only with these two.
        clientKind={kind}
        outOfScope={outOfScope}
        canOpenCall={canOpenCall}
        canExclude={canImport}
        onClose={() => setTracked(null)}
        onReview={
          canReview
            ? (row) => {
                setTracked(null)
                setPicked(row)
              }
            : undefined
        }
      />
      <ReviewModal sale={picked} windowDays={windowDays} onClose={() => setPicked(null)} />
      <ImportModal open={importOpen} onOpenChange={setImportOpen} />
      <BranchesModal open={branchesOpen} onOpenChange={setBranchesOpen} canEdit={canImport} />
      <DigestModal open={digestOpen} onOpenChange={setDigestOpen} />
    </Page>
  )
}
