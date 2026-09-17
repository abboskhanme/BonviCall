/**
 * `/analysis` — the scored-call list (SPEC-ANALYTICS §7.3).
 *
 * Newest conversation first, the same `started_at desc` the calls list settled
 * on and for the same reason: a recovery sweep uploading yesterday's calls
 * after today's otherwise fills the top of the page with old conversations.
 *
 * **A row links to `/analysis/:callId` and not into the calls module.** One
 * product, two sections, and phase 1 keeps the seam clean (§7): nothing in
 * `modules/calls` is touched by this work, so a mistake here cannot reach a
 * screen the fleet already depends on.
 *
 * Loading, empty and error are `QueryBoundary`'s, not this page's
 * (CONVENTIONS-CLIENT.md §2), and the screen state — every filter, and the
 * cursor — lives in the URL, so a filtered list is a link somebody can paste.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, FilterX, ListChecks } from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import {
  EM_DASH,
  formatCount,
  formatDateTime,
  formatDuration,
  formatInstantTitle,
  formatPhone,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { DateFilter, EnumFilter, FilterField, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  PAGE_SIZE,
  useAnalysisPage,
  type AnalysisListItem,
  type AnalysisListQuery,
  type AnalysisPage,
  type AnalysisStage,
  type ScoreBand,
} from './api'
import {
  BAND_LABEL,
  BAND_TONE,
  bandOf,
  FAILURE_LABEL,
  redFlagLabel,
  STAGE_LABEL,
  STAGE_TONE,
} from './labels'

/** The URL is the screen state (CONVENTIONS-CLIENT.md §2), and the parameter
 *  names are the server's own — `AnalysisFilters` in `analysis/schemas.py`. */
const PARAM_AGENT = 'agent_id'
const PARAM_STAGE = 'stage'
const PARAM_BAND = 'score_band'
const PARAM_REVIEW = 'needs_review'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'
const PARAM_CURSOR = 'cursor'

/** Every filter parameter, so "clear" cannot miss one — the bug where a reset
 *  button leaves a hidden filter in force. */
const FILTER_PARAMS = [
  PARAM_AGENT,
  PARAM_STAGE,
  PARAM_BAND,
  PARAM_REVIEW,
  PARAM_DATE_FROM,
  PARAM_DATE_TO,
] as const

/**
 * Read a closed enum out of the URL.
 *
 * A pasted `?stage=nearly` must not be forwarded as a 422 somebody cannot act
 * on; an unknown value is simply no filter. The allowed set comes from the
 * label map, which is keyed by the generated union, so this cannot drift.
 */
function parseEnum<T extends string>(
  raw: string | null,
  allowed: Record<T, unknown>,
): T | undefined {
  return raw !== null && raw in allowed ? (raw as T) : undefined
}

/** The review queue is a flag, and only its "on" position is a filter: "show me
 *  everything except the ones needing review" is not a question anybody asks. */
function parseReview(raw: string | null): true | undefined {
  return raw === 'true' ? true : undefined
}

/**
 * The score cell.
 *
 * A queued or skipped row has no number yet and that is not a gap to fill —
 * `overall_score` is null until the call is scored, and the stage column beside
 * it already says why. The band colour comes from `bandOf`, never from a second
 * opinion about what "good" means.
 */
function ScoreCell({ item }: { item: AnalysisListItem }) {
  if (item.overall_score === null) {
    return <span className="text-muted">{EM_DASH}</span>
  }
  const band = bandOf(item.overall_score)
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className="font-mono text-sm font-semibold tabular-nums text-text">
        {item.overall_score}
      </span>
      <Badge tone={BAND_TONE[band]}>{t(BAND_LABEL[band])}</Badge>
    </span>
  )
}

/** At most this many chips before the rest become "+2". A row that wraps to
 *  four lines because one call collected six breaches is a row nobody scans. */
const MAX_CHIPS = 2

function FlagCell({ item }: { item: AnalysisListItem }) {
  if (item.red_flag_types.length === 0 && !item.needs_review) {
    return <span className="text-muted">{EM_DASH}</span>
  }
  const shown = item.red_flag_types.slice(0, MAX_CHIPS)
  const rest = item.red_flag_types.length - shown.length
  return (
    <span className="flex flex-wrap items-center gap-1">
      {/* Worth a person's time, and not the same statement as a breach: a
          score can need review with no red flag at all (low confidence, a
          short transcript), which is four of the six reasons in `rules.py`. */}
      {item.needs_review ? <Badge tone="warn">{t('analysis.reviewBadge')}</Badge> : null}
      {shown.map((type) => (
        <Badge key={type} tone="bad">
          {redFlagLabel(type)}
        </Badge>
      ))}
      {rest > 0 ? <Badge tone="neutral">{t('analysis.moreFlags', { count: rest })}</Badge> : null}
    </span>
  )
}

function StageCell({ item }: { item: AnalysisListItem }) {
  return (
    <span className="flex flex-col gap-0.5">
      <Badge tone={STAGE_TONE[item.stage]}>{t(STAGE_LABEL[item.stage])}</Badge>
      {/* A skipped or failed row carries its reason in the same cell: "why is
          this call not scored" is the question this column exists for, and a
          bare "O'tkazib yuborilgan" answers none of it. */}
      {item.failure_code ? (
        <span className="text-2xs text-muted">{t(FAILURE_LABEL[item.failure_code])}</span>
      ) : null}
    </span>
  )
}

function AnalysisRows({ page, showAgent }: { page: AnalysisPage; showAgent: boolean }) {
  const navigate = useNavigate()

  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            <TH>{t('analysis.colTime')}</TH>
            {showAgent ? <TH>{t('analysis.colAgent')}</TH> : null}
            <TH>{t('analysis.colRemote')}</TH>
            <TH className="text-end">{t('analysis.colDuration')}</TH>
            <TH>{t('analysis.colScore')}</TH>
            <TH>{t('analysis.colFlags')}</TH>
            <TH>{t('analysis.colStage')}</TH>
          </tr>
        </THead>
        <TBody>
          {page.items.map((item) => {
            const call = item.call
            const phone = formatPhone(call.remote_number)
            return (
              <TR
                key={call.call_id}
                interactive
                onClick={() => navigate(`/analysis/${call.call_id}`)}
              >
                {/* The whole row is clickable for a mouse, and this cell is the
                    real link — the keyboard path into the card. */}
                <TD className="whitespace-nowrap" title={formatInstantTitle(call.started_at)}>
                  <Link
                    to={`/analysis/${call.call_id}`}
                    className="text-muted underline-offset-2 hover:text-accent hover:underline"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {formatDateTime(call.started_at)}
                  </Link>
                </TD>
                {/* `agent_name` is resolved server-side, exactly as
                    `CallResponse` resolves it: a name lookup per row in the
                    browser is the N+1 problem with a different owner. */}
                {showAgent ? <TD className="whitespace-nowrap">{call.agent_name}</TD> : null}
                <TD className="whitespace-nowrap">
                  <span className="font-mono">{phone ?? t('analysis.numberWithheld')}</span>
                </TD>
                <TD className="whitespace-nowrap text-end font-mono tabular-nums">
                  {formatDuration(call.duration_sec)}
                </TD>
                <TD>
                  <ScoreCell item={item} />
                </TD>
                <TD className="max-w-[18rem]">
                  <FlagCell item={item} />
                </TD>
                <TD>
                  <StageCell item={item} />
                </TD>
              </TR>
            )
          })}
        </TBody>
      </Table>
    </TableWrap>
  )
}

export function AnalysisListPage() {
  const can = useAuth((state) => state.can)
  // `analysis:read` is held by `admin` and `manager` only (§6.1), and both see
  // every agent — so unlike the calls list there is no own-scope case here. The
  // column follows the roster permission because that is what fills its filter.
  const showAgent = can(Perm.AGENTS_READ)

  const [searchParams, setSearchParams] = useSearchParams()
  const agentId = searchParams.get(PARAM_AGENT) ?? undefined
  const stage = parseEnum<AnalysisStage>(searchParams.get(PARAM_STAGE), STAGE_LABEL)
  const band = parseEnum<ScoreBand>(searchParams.get(PARAM_BAND), BAND_LABEL)
  const needsReview = parseReview(searchParams.get(PARAM_REVIEW))
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const cursor = searchParams.get(PARAM_CURSOR) ?? undefined

  /**
   * The trail of cursors already visited, so "previous" works.
   *
   * A keyset cursor points into a moving stream and only goes forward, so there
   * is no page number to put in the URL. The current page IS in the URL, which
   * is what makes a row linkable; the trail is component state, and a pasted
   * deep link starts a fresh one.
   */
  const [trail, setTrail] = useState<string[]>([])
  const [heldTotal, setHeldTotal] = useState<{ key: string; total: number } | null>(null)

  const query: AnalysisListQuery = {
    limit: PAGE_SIZE,
    ...(cursor ? { cursor } : {}),
    // Repeated parameters on the wire — the server declares `list[...]` for all
    // three, and a comma-joined string would be a 422.
    ...(agentId ? { agent_id: [agentId] } : {}),
    ...(stage ? { stage: [stage] } : {}),
    ...(band ? { score_band: [band] } : {}),
    ...(needsReview ? { needs_review: true } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    // A COUNT over a filtered table is affordable once per filter change and
    // not once per page, so only the first page asks (SPEC §4.0).
    with_total: cursor === undefined,
  }

  const listQuery = useAnalysisPage(query)
  const agentsQuery = useAgentDirectory(showAgent)

  const filtered = FILTER_PARAMS.some((param) => searchParams.get(param) !== null)

  /** Every filter as one string — what a held total may outlive (paging) and
   *  what it may not (any filter change). The cursor is deliberately absent:
   *  that is the thing it has to survive. */
  const filterKey = FILTER_PARAMS.map((param) => searchParams.get(param) ?? '').join(' ')

  function applyFilters(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    // Any filter change invalidates every cursor taken under the old filter.
    next.delete(PARAM_CURSOR)
    setTrail([])
    setSearchParams(next, { replace: true })
  }

  function applyFilter(key: string, value: string | null) {
    applyFilters({ [key]: value })
  }

  function goToCursor(nextCursor: string | null, nextTrail: string[]) {
    const next = new URLSearchParams(searchParams)
    if (nextCursor === null) next.delete(PARAM_CURSOR)
    else next.set(PARAM_CURSOR, nextCursor)
    setTrail(nextTrail)
    setSearchParams(next)
  }

  const pageTotal = listQuery.data?.total
  useEffect(() => {
    if (typeof pageTotal === 'number') setHeldTotal({ key: filterKey, total: pageTotal })
  }, [pageTotal, filterKey])

  const total =
    typeof pageTotal === 'number'
      ? pageTotal
      : heldTotal?.key === filterKey
        ? heldTotal.total
        : undefined

  return (
    <Page>
      <PageHeader
        title={t('page.analysis')}
        description={t('analysis.listSubtitle')}
        actions={
          <Link
            to="/analysis/queue"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ListChecks className="size-4" aria-hidden />
            {t('analysis.openQueue')}
          </Link>
        }
      />

      <Card className="flex flex-wrap items-end gap-2 p-3">
        {showAgent ? (
          <FilterField label={t('analysis.filterAgent')}>
            <select
              className={SELECT_CLASS}
              value={agentId ?? ''}
              onChange={(event) => applyFilter(PARAM_AGENT, event.target.value || null)}
            >
              <option value="">{t('analysis.filterAgentAll')}</option>
              {(agentsQuery.data?.items ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.full_name}
                </option>
              ))}
            </select>
          </FilterField>
        ) : null}

        <EnumFilter
          label={t('analysis.filterStage')}
          allLabel={t('analysis.filterAny')}
          labels={STAGE_LABEL}
          value={stage}
          onChange={(value) => applyFilter(PARAM_STAGE, value)}
        />
        {/* The four band NAMES, never a pair of numbers: the thresholds are the
            server's (`SCORE_BAND_RANGE`, derived from `ScoreSummary.grade`), so
            the browser never has to know where a band starts. */}
        <EnumFilter
          label={t('analysis.filterBand')}
          allLabel={t('analysis.filterAny')}
          labels={BAND_LABEL}
          value={band}
          onChange={(value) => applyFilter(PARAM_BAND, value)}
        />

        <FilterField label={t('analysis.filterReview')}>
          <select
            className={SELECT_CLASS}
            value={needsReview ? 'true' : ''}
            onChange={(event) => applyFilter(PARAM_REVIEW, event.target.value || null)}
          >
            <option value="">{t('analysis.filterAny')}</option>
            <option value="true">{t('analysis.filterReviewOnly')}</option>
          </select>
        </FilterField>

        {/* Asia/Tashkent calendar dates, inclusive at both ends, each bound
            standing on its own exactly as it does on the calls list. */}
        <DateFilter
          label={t('analysis.filterDateFrom')}
          hint={t('analysis.filterDateEmpty')}
          pickLabel={t('analysis.filterDatePickFrom')}
          clearLabel={t('analysis.filterDateClearFrom')}
          value={dateFrom}
          max={dateTo}
          onChange={(value) => applyFilter(PARAM_DATE_FROM, value)}
        />
        <DateFilter
          label={t('analysis.filterDateTo')}
          hint={t('analysis.filterDateEmpty')}
          pickLabel={t('analysis.filterDatePickTo')}
          clearLabel={t('analysis.filterDateClearTo')}
          value={dateTo}
          min={dateFrom}
          onChange={(value) => applyFilter(PARAM_DATE_TO, value)}
        />

        <span className="ms-auto whitespace-nowrap text-xs text-muted">
          {typeof total === 'number' ? t('analysis.total', { count: formatCount(total) }) : EM_DASH}
        </span>

        {filtered ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const next = new URLSearchParams(searchParams)
              for (const param of FILTER_PARAMS) next.delete(param)
              next.delete(PARAM_CURSOR)
              setTrail([])
              setSearchParams(next, { replace: true })
            }}
          >
            <FilterX className="size-4" aria-hidden />
            {t('analysis.filterReset')}
          </Button>
        ) : null}
      </Card>

      <QueryBoundary
        query={listQuery}
        isEmpty={(page) => page.items.length === 0}
        // Three different sentences, never one generic line (SPEC §5.3). The
        // unfiltered one carries the case this deployment is actually in today:
        // `analysis.enabled` is seeded false, so nothing has been queued and
        // the honest answer is "the module has not run yet", with the page that
        // says whether it is switched on one click away.
        emptyTitle={filtered ? t('analysis.emptyFiltered') : t('analysis.emptyAll')}
        emptyHint={filtered ? t('analysis.emptyFilteredHint') : t('analysis.emptyAllHint')}
        emptyAction={
          filtered ? undefined : (
            <Link
              to="/analysis/queue"
              className="text-xs text-accent underline-offset-2 hover:underline"
            >
              {t('analysis.openQueue')}
            </Link>
          )
        }
        skeletonRows={8}
      >
        {(page) => (
          <>
            <AnalysisRows page={page} showAgent={showAgent} />

            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {t('analysis.shown', { count: formatCount(page.items.length) })}
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
                  {t('analysis.prevPage')}
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
                  {t('analysis.nextPage')}
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
