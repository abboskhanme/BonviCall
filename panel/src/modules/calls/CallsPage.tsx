/**
 * `/calls` — the call list (T28, SPEC §5.2).
 *
 * The columns are the ones a rollout is judged by: when the call happened, which
 * way it went, who was on the other end, how long it lasted, and **whether
 * there is a recording — and if not, why**. UC-14 guarantees the call is logged
 * either way and that the reason comes from a closed enum, so the audio column
 * always says something. A blank cell there would be the panel refusing to
 * answer the one question it was built to answer.
 *
 * Scope: a `sales` user reaches this page through `calls:read:own` and the
 * SERVER narrows the rows (`CallService.list`). The panel does not re-implement
 * that rule — it only hides the agent column, which is presentation, not access
 * control (CONVENTIONS-CLIENT.md §2, CONVENTIONS.md §11).
 *
 * Loading, empty and error are `QueryBoundary`'s, not this page's.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileArchive,
  FilterX,
  PhoneIncoming,
  PhoneOutgoing,
} from 'lucide-react'

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
import { ExportCallsModal } from './ExportCallsModal'
import {
  DateFilter,
  EnumFilter,
  FilterField,
  SearchFilter,
  SELECT_CLASS,
} from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { useAgentDirectory } from '@/modules/agents/api'

import {
  callsAudioArchiveUrl,
  useCallsPage,
  PAGE_SIZE,
  type Call,
  type CallListQuery,
  type CallPage,
} from './api'
import { downloadExport } from './export'
import { searchParamFor } from './search'
import {
  audioState,
  audioStateLabel,
  audioStateTone,
  CALL_TYPE_FILTER_LABEL,
  CALL_TYPE_LABEL,
  DIRECTION_LABEL,
  DISPOSITION_LABEL,
  DISPOSITION_TONE,
} from './labels'

/**
 * The URL is the screen state (CONVENTIONS-CLIENT.md §2), and the parameter
 * names are the server's own, so a filtered list is a link somebody can paste
 * into a chat and a colleague opens the same page.
 *
 * These are the filters of SPEC §4.7 that a person reaches for on this page.
 * The contract carries more — `capture_route[]`, `audio_missing_reason[]`,
 * `device_model`, `app_variant`, `min/max_duration_sec`, `number_id[]` — and
 * `CallListQuery` already types every one of them; they are deliberately not
 * surfaced here because they are the gap report's questions (UC-23), not this
 * page's, and a filter bar nobody can read is worse than one filter fewer.
 */
const PARAM_AGENT = 'agent_id'
const PARAM_AUDIO = 'has_audio'
const PARAM_DIRECTION = 'direction'
const PARAM_DISPOSITION = 'disposition'
const PARAM_CALL_TYPE = 'call_type'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'
const PARAM_CURSOR = 'cursor'

/**
 * The one exception to "the parameter names are the server's own".
 *
 * The search box is a single field over TWO server parameters — `q` (contact
 * name) and `remote_number` — and `./search.ts` decides which one a given
 * input becomes. Calling the URL parameter `q` would therefore be a lie half
 * the time: `?q=901112233` would travel to the server as `remote_number`.
 * `search` names what it actually holds — what somebody typed in the box —
 * and the routing rule stays in one readable place.
 *
 * The page-size `limit=` an old link may carry is simply ignored — the page
 * size is a constant now.
 */
const PARAM_SEARCH = 'search'

/**
 * The two names the search used to have, still read — once, as a fallback.
 *
 * Somebody has `?q=Nodira` in a chat message or a bookmark. Ignoring it would
 * open an UNFILTERED list that looks exactly like a filtered one that found a
 * lot, which is the worst kind of wrong answer: silent. Reading them keeps the
 * old link meaning what it meant. `search` wins where both are present, and
 * touching the box rewrites the URL to `search`, so the legacy names fade out
 * on their own rather than being maintained forever.
 */
const LEGACY_PARAM_Q = 'q'
const LEGACY_PARAM_REMOTE = 'remote_number'

/** Every filter parameter, so "clear" and "is anything filtered" cannot miss
 *  one — the bug where a reset button leaves a hidden filter behind. The two
 *  legacy names are in here for exactly that reason: a filter that is in force
 *  must be a filter "clear" removes. */
const FILTER_PARAMS = [
  PARAM_AGENT,
  PARAM_AUDIO,
  PARAM_DIRECTION,
  PARAM_DISPOSITION,
  PARAM_CALL_TYPE,
  PARAM_DATE_FROM,
  PARAM_DATE_TO,
  PARAM_SEARCH,
  LEGACY_PARAM_Q,
  LEGACY_PARAM_REMOTE,
] as const

/**
 * Read a closed enum out of the URL.
 *
 * A pasted `?direction=sideways` must not be forwarded to the server as a 422;
 * an unknown value is simply no filter. The allowed set comes from the label
 * map, which is itself keyed by the generated union, so this cannot drift.
 */
function parseEnum<T extends string>(
  raw: string | null,
  allowed: Record<T, unknown>,
): T | undefined {
  return raw !== null && raw in allowed ? (raw as T) : undefined
}

/** `'true' | 'false' | null` → the tri-state the server's `has_audio` is. */
function parseHasAudio(raw: string | null): boolean | undefined {
  if (raw === 'true') return true
  if (raw === 'false') return false
  return undefined
}

/**
 * The audio cell.
 *
 * Three answers, not two. "There is no recording because retention deleted it
 * after a year" and "there is no recording because capture failed" are
 * different sentences and only the second one is a problem — see
 * `audioState()` in ./labels for why collapsing them corrupts the gap report.
 */
function AudioCell({ call }: { call: Call }) {
  const state = audioState(call.audio)
  return (
    <Badge tone={audioStateTone(state)}>{t(audioStateLabel(state))}</Badge>
  )
}

function DirectionCell({ call }: { call: Call }) {
  const Icon = call.direction === 'incoming' ? PhoneIncoming : PhoneOutgoing
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <Icon className="size-3.5 shrink-0 text-muted" aria-hidden />
      <span>{t(DIRECTION_LABEL[call.direction])}</span>
    </span>
  )
}

function CallRows({ page, showAgent }: { page: CallPage; showAgent: boolean }) {
  const navigate = useNavigate()

  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            <TH>{t('calls.colTime')}</TH>
            {/* The list is ordered by this column — the CALL's own time,
                newest first. `received_at` is still shown beside it, because
                the two differ whenever a phone was off or a recovery sweep
                found an old call, and a reader who cannot see both has no way
                to tell a late upload from a wrong clock (SPEC §3.12). */}
            <TH title={t('calls.colReceivedHint')}>{t('calls.colReceived')}</TH>
            {/* Third: who the call belongs to comes before what the call was.
                Hidden for own-scope, where it would be one repeated name, and
                the remaining eight columns simply close up. */}
            {showAgent ? <TH>{t('calls.colAgent')}</TH> : null}
            <TH>{t('calls.colDirection')}</TH>
            <TH>{t('calls.colRemote')}</TH>
            {/* The name is what people scan this list for, so it is a column
                and not a grey suffix inside the number cell. Unconditional,
                unlike the agent column: a `sales` user reading their own calls
                needs it most of all. */}
            <TH>{t('calls.colContact')}</TH>
            <TH>{t('calls.colStatus')}</TH>
            <TH className="text-end">{t('calls.colDuration')}</TH>
            <TH>{t('calls.colAudio')}</TH>
          </tr>
        </THead>
        <TBody>
          {page.items.map((call) => {
            const phone = formatPhone(call.remote_number)
            return (
              <TR key={call.id} interactive onClick={() => navigate(`/calls/${call.id}`)}>
                {/* The whole row is clickable for a mouse, but the link is
                    real: a `role="link"` on a <tr> would break the table for a
                    screen reader and a bare onClick is unreachable from a
                    keyboard. This cell is the keyboard path into the card. */}
                <TD className="whitespace-nowrap" title={formatInstantTitle(call.started_at)}>
                  <Link
                    to={`/calls/${call.id}`}
                    className="text-muted underline-offset-2 hover:text-accent hover:underline"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {formatDateTime(call.started_at)}
                  </Link>
                </TD>
                <TD
                  className="whitespace-nowrap text-xs text-muted"
                  title={formatInstantTitle(call.received_at)}
                >
                  {formatDateTime(call.received_at)}
                </TD>
                {/* `agent_name` is resolved server-side (SPEC §4.7): looking
                    a name up per row in the browser is the N+1 problem
                    relocated to the client. Third, with its header. */}
                {showAgent ? <TD className="whitespace-nowrap">{call.agent_name}</TD> : null}
                <TD>
                  <DirectionCell call={call} />
                </TD>
                {/* A phone number is a single token. With a free-text
                    column beside it, an unconstrained cell is the one the
                    table takes its slack from, and a number broken across two
                    lines doubles the height of every row. */}
                <TD className="whitespace-nowrap">
                  <span className="font-mono">{phone ?? t('calls.numberWithheld')}</span>
                </TD>
                {/* A name long enough to push the audio column off a 1440px
                    screen is truncated rather than allowed to widen the table;
                    the `title` still carries all of it. An absent name is the
                    em dash the rest of the product uses, never a blank cell
                    (`shared/ui/detail.tsx`). */}
                <TD
                  className="max-w-[14rem] truncate"
                  title={call.contact_name ?? undefined}
                >
                  {call.contact_name ?? <span className="text-muted">{EM_DASH}</span>}
                </TD>
                {/* Four short labels that name WHO did not pick up ("Xodim
                    javob bermadi" / "Mijoz javob bermadi"), so they are read
                    as a phrase or not at all — a badge broken across three
                    lines is what made the rows grow at 1280px. The audio cell
                    below is deliberately NOT pinned this way: its labels are
                    whole sentences and holding them on one line would push the
                    table into a horizontal scroll. */}
                <TD className="whitespace-nowrap">
                  <Badge tone={DISPOSITION_TONE[call.disposition]}>
                    {t(DISPOSITION_LABEL[call.disposition])}
                  </Badge>
                </TD>
                <TD className="whitespace-nowrap text-end font-mono tabular-nums">
                  {formatDuration(call.duration_sec)}
                </TD>
                <TD>
                  <AudioCell call={call} />
                </TD>
              </TR>
            )
          })}
        </TBody>
      </Table>
    </TableWrap>
  )
}

export function CallsPage() {
  const can = useAuth((state) => state.can)
  // Full `calls:read` sees everybody; `calls:read:own` sees one agent — their
  // own — so the column would be one repeated name (SPEC §5.2).
  const showAgent = can(Perm.CALLS_READ)

  const [searchParams, setSearchParams] = useSearchParams()
  const agentId = searchParams.get(PARAM_AGENT) ?? undefined
  const hasAudio = parseHasAudio(searchParams.get(PARAM_AUDIO))
  const direction = parseEnum(searchParams.get(PARAM_DIRECTION), DIRECTION_LABEL)
  const disposition = parseEnum(searchParams.get(PARAM_DISPOSITION), DISPOSITION_LABEL)
  // Parsed against the FILTER's map, not the full enum: this page can only
  // send a value it can also show, so a pasted `?call_type=unknown` is no
  // filter rather than a filter with no matching option in the select.
  const callType = parseEnum(searchParams.get(PARAM_CALL_TYPE), CALL_TYPE_FILTER_LABEL)
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const search =
    searchParams.get(PARAM_SEARCH) ??
    searchParams.get(LEGACY_PARAM_Q) ??
    searchParams.get(LEGACY_PARAM_REMOTE) ??
    undefined
  const cursor = searchParams.get(PARAM_CURSOR) ?? undefined

  // One box, two server parameters. The rule is a pure function with its own
  // test (`./search.ts`) rather than a condition inlined here.
  const searchFilter = searchParamFor(search ?? '')

  /**
   * The trail of cursors already visited, so "previous" works.
   *
   * A keyset cursor points into a moving stream and only ever goes forward, so
   * there is no page number to put in the URL and no way to reconstruct page
   * N−1 from page N. The current page IS in the URL, which is what makes a row
   * linkable; the trail is component state, and a pasted deep link starts a
   * fresh trail — from that page, "previous" returns to the first page rather
   * than lying about where the reader came from.
   */
  const [trail, setTrail] = useState<string[]>([])
  const [exporting, setExporting] = useState(false)
  const [archiving, setArchiving] = useState(false)

  /**
   * The last total the server gave, and which filter it was the total OF.
   *
   * Only the first page asks for a count (`with_total` below), so every page
   * after it answers `total: null`. That was invisible while a page held 1000
   * rows; with 50 a reader reaches page two twenty times sooner and watches
   * "Jami: 742 ta" turn into a dash, which reads as a number that got lost.
   *
   * Holding it costs no request. Holding it across a FILTER change would be a
   * lie, so the filter it belongs to is stored with it and compared — a count
   * from the previous filter is worse than no count.
   */
  const [heldTotal, setHeldTotal] = useState<{ key: string; total: number } | null>(null)

  const query: CallListQuery = {
    limit: PAGE_SIZE,
    // ═══ Ordered by WHEN THE CALL HAPPENED, newest first ═══════════════════
    //
    // The server's default is `received_at` — when the upload landed — and
    // SPEC §3.12 has the reason: devices lie about time, and receipt order is
    // the one this server can vouch for. It reads wrong on a real fleet.
    // Recovery sweeps upload yesterday's calls after today's (UC-13), and a
    // phone that was off all morning arrives at lunchtime, so the top of the
    // page kept filling with old conversations while the call somebody made
    // five minutes ago sat further down. To a reader, that IS the list being
    // broken.
    //
    // So the page asks for `started_at desc`. Both columns are still shown
    // and the skew stays visible beside them, which is what makes a wrong
    // device clock diagnosable rather than merely confusing. Paging stays
    // exact: the server pairs every sort with `id` (SPEC §4.7), so a keyset
    // page never repeats or skips a row whose timestamp ties.
    sort: 'started_at',
    order: 'desc',
    ...(cursor ? { cursor } : {}),
    // `agent_id` is a repeated parameter on the wire; the picker chooses one
    // agent, so it goes as a one-element list rather than as a bare string.
    ...(agentId ? { agent_id: [agentId] } : {}),
    ...(hasAudio === undefined ? {} : { has_audio: hasAudio }),
    ...(direction ? { direction } : {}),
    ...(disposition ? { disposition } : {}),
    ...(callType ? { call_type: callType } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    // Either `{ q }` or `{ remote_number }` — never both, never neither with
    // an empty string in it.
    ...(searchFilter ?? {}),
    // SPEC §4.0: a COUNT(*) over a filtered 500k table is affordable once per
    // filter change and not once per page, so only the first page asks.
    with_total: cursor === undefined,
  }

  const callsQuery = useCallsPage(query)

  /**
   * How many rows on this page actually have a recording.
   *
   * The button says it, and is disabled at zero. Without that, pressing it on
   * a page where nothing was recorded hands over an archive containing only
   * `manifest.csv` — which is correct, and reads exactly like a broken
   * download. The manifest explains it, but nobody opens a file to find out
   * why the file they wanted is missing. The count belongs where the decision
   * is made, which is before the click.
   */
  const recordingsOnPage =
    callsQuery.data?.items.filter((call) => call.has_audio).length ?? 0
  // Only the filter's option list needs the roster now that `agent_name`
  // arrives with the row. A `sales` user holds neither the permission nor the
  // filter, so nothing is requested for them.
  const agentsQuery = useAgentDirectory(showAgent && can(Perm.AGENTS_READ))

  const filtered = FILTER_PARAMS.some((param) => searchParams.get(param) !== null)

  /** Every filter as one string — what the held total is allowed to outlive
   *  (paging) and what it is not (any filter change). The cursor is
   *  deliberately absent: that is the thing it must survive. The separator is
   *  written as an escape and is a character no filter value can contain, so
   *  `a` + `b` cannot collide with `ab` (`shared/lib/format.ts` gives the same
   *  reason for never typing an invisible character into a source file). */
  const filterKey = FILTER_PARAMS.map((param) => searchParams.get(param) ?? '').join('\u0000')

  /**
   * Write filters to the URL — one navigation, however many changed.
   *
   * Takes a set rather than a single key because two of them move together:
   * the date range clears both ends at once, and doing that as two calls would
   * be two history entries and two requests for one click.
   */
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

  const pageTotal = callsQuery.data?.total
  useEffect(() => {
    if (typeof pageTotal === 'number') setHeldTotal({ key: filterKey, total: pageTotal })
  }, [pageTotal, filterKey])

  const total =
    typeof pageTotal === 'number'
      ? pageTotal
      : heldTotal?.key === filterKey
        ? heldTotal.total
        : undefined

  /**
   * The filters in force, in Uzbek, for the export dialog to read back.
   *
   * Built from the SAME values the query object carries, so what the dialog
   * promises and what the server receives cannot disagree.
   */
  const filterSummary: string[] = [
    agentId
      ? t('calls.exportFilterAgent', {
          name:
            (agentsQuery.data?.items ?? []).find((agent) => agent.id === agentId)?.full_name ??
            agentId,
        })
      : null,
    direction ? t('calls.exportFilterOne', {
      field: t('calls.filterDirection'),
      value: t(DIRECTION_LABEL[direction]),
    }) : null,
    disposition ? t('calls.exportFilterOne', {
      field: t('calls.filterDisposition'),
      value: t(DISPOSITION_LABEL[disposition]),
    }) : null,
    callType ? t('calls.exportFilterOne', {
      field: t('calls.filterCallType'),
      value: t(CALL_TYPE_LABEL[callType]),
    }) : null,
    hasAudio === undefined
      ? null
      : t('calls.exportFilterOne', {
          field: t('calls.filterAudio'),
          value: t(hasAudio ? 'calls.filterAudioWith' : 'calls.filterAudioWithout'),
        }),
    dateFrom ? t('calls.exportFilterOne', { field: t('calls.filterDateFrom'), value: dateFrom }) : null,
    dateTo ? t('calls.exportFilterOne', { field: t('calls.filterDateTo'), value: dateTo }) : null,
    // The dialog names the field the search actually became, not the box it
    // was typed into: "Raqam bo'yicha: 901112233" is what the server was asked,
    // and a dialog that promises something else is the bug UC-22 is about.
    searchFilter === null
      ? null
      : 'remote_number' in searchFilter
        ? t('calls.exportFilterOne', {
            field: t('calls.filterRemoteNumber'),
            value: searchFilter.remote_number,
          })
        : t('calls.exportFilterOne', {
            field: t('calls.filterContact'),
            value: searchFilter.q,
          }),
  ].filter((line): line is string => line !== null)

  return (
    <Page>
      <PageHeader
        title={t('page.calls')}
        description={showAgent ? undefined : t('calls.ownScopeNote')}
        actions={
          <>
            {/* Two different downloads, and the labels have to say which is
                which: one is the rows of every call the filter matches, the
                other is the recordings of the fifty on screen. */}
            {can(Perm.AUDIO_DOWNLOAD) ? (
              <Button
                variant="secondary"
                size="sm"
                disabled={archiving || recordingsOnPage === 0}
                title={
                  recordingsOnPage === 0 ? t('calls.audioArchiveNone') : undefined
                }
                onClick={() => {
                  setArchiving(true)
                  void downloadExport(callsAudioArchiveUrl(query)).finally(() =>
                    setArchiving(false),
                  )
                }}
              >
                <FileArchive className="size-4" aria-hidden />
                {archiving
                  ? t('calls.audioArchiveBusy')
                  : recordingsOnPage === 0
                    ? t('calls.audioArchiveNone')
                    : t('calls.audioArchive', { count: recordingsOnPage })}
              </Button>
            ) : null}
            {can(Perm.REPORTS_EXPORT) ? (
              <Button variant="secondary" size="sm" onClick={() => setExporting(true)}>
                <Download className="size-4" aria-hidden />
                {t('calls.export')}
              </Button>
            ) : null}
          </>
        }
      />

      {/*
        Two rows, and the split is the point. The search is the control people
        reach for; the rest refine what it returned. Giving all seven the same
        size is what made this bar read as a form somebody grew one field at a
        time.
      */}
      <Card className="flex flex-col gap-3 p-3">
        <div className="flex flex-wrap items-center gap-3">
          <SearchFilter
            label={t('calls.search')}
            placeholder={t('calls.searchHint')}
            clearLabel={t('calls.searchClear')}
            value={search}
            // Writing the box also retires the legacy names: leaving `q=`
            // behind would resurrect the old filter the moment the box is
            // cleared, because the fallback would read it again.
            onCommit={(value) =>
              applyFilters({
                [PARAM_SEARCH]: value,
                [LEGACY_PARAM_Q]: null,
                [LEGACY_PARAM_REMOTE]: null,
              })
            }
            className="min-w-[16rem] flex-1 sm:max-w-md"
          />
          {/* The count belongs beside the search rather than at the end of the
              filters: it is the answer to everything in this bar at once. */}
          <span className="ms-auto whitespace-nowrap text-xs text-muted">
            {typeof total === 'number' ? t('calls.total', { count: formatCount(total) }) : EM_DASH}
          </span>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
          {showAgent ? (
            <FilterField label={t('calls.filterAgent')}>
              <select
                className={SELECT_CLASS}
                value={agentId ?? ''}
                onChange={(event) => applyFilter(PARAM_AGENT, event.target.value || null)}
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

          <EnumFilter
            label={t('calls.filterDirection')}
            allLabel={t('calls.filterAny')}
            labels={DIRECTION_LABEL}
            value={direction}
            onChange={(value) => applyFilter(PARAM_DIRECTION, value)}
          />
          <EnumFilter
            label={t('calls.filterDisposition')}
            allLabel={t('calls.filterAny')}
            labels={DISPOSITION_LABEL}
            value={disposition}
            onChange={(value) => applyFilter(PARAM_DISPOSITION, value)}
          />
          <EnumFilter
            label={t('calls.filterCallType')}
            allLabel={t('calls.filterAny')}
            labels={CALL_TYPE_FILTER_LABEL}
            value={callType}
            onChange={(value) => applyFilter(PARAM_CALL_TYPE, value)}
          />

          <FilterField label={t('calls.filterAudio')}>
            <select
              className={SELECT_CLASS}
              value={hasAudio === undefined ? '' : String(hasAudio)}
              onChange={(event) => applyFilter(PARAM_AUDIO, event.target.value || null)}
            >
              <option value="">{t('calls.filterAny')}</option>
              <option value="true">{t('calls.filterAudioWith')}</option>
              <option value="false">{t('calls.filterAudioWithout')}</option>
            </select>
          </FilterField>

          {/* Asia/Tashkent calendar dates, inclusive on both ends (SPEC §4.7).
              Still a native `<input type="date">` underneath — it sends
              `yyyy-mm-dd`, which is exactly what the server parses, and it is
              the only picker that is accessible and localised for free. */}
          {/* Two independent bounds, each applying the moment it is picked.
              `max`/`min` cross-constrain them so the picker cannot offer a
              start after the chosen end, but neither waits for the other: a
              start alone is "since then", an end alone is "up to then", which
              is exactly how the server reads a missing bound. */}
          <DateFilter
            label={t('calls.filterDateFrom')}
            hint={t('calls.filterDateEmpty')}
            pickLabel={t('calls.filterDatePickFrom')}
            clearLabel={t('calls.filterDateClearFrom')}
            value={dateFrom}
            max={dateTo}
            onChange={(value) => applyFilter(PARAM_DATE_FROM, value)}
          />
          <DateFilter
            label={t('calls.filterDateTo')}
            hint={t('calls.filterDateEmpty')}
            pickLabel={t('calls.filterDatePickTo')}
            clearLabel={t('calls.filterDateClearTo')}
            value={dateTo}
            min={dateFrom}
            onChange={(value) => applyFilter(PARAM_DATE_TO, value)}
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
              {t('calls.filterReset')}
            </Button>
          ) : null}
        </div>
      </Card>

      <QueryBoundary
        query={callsQuery}
        isEmpty={(page) => page.items.length === 0}
        // "No calls yet" and "nothing matches this filter" are different
        // sentences and must stay different (SPEC §5.3).
        emptyTitle={filtered ? t('calls.emptyFiltered') : t('calls.emptyAll')}
        emptyHint={filtered ? t('calls.emptyFilteredHint') : t('calls.emptyAllHint')}
        skeletonRows={8}
      >
        {(page) => (
          <>
            <CallRows page={page} showAgent={showAgent} />

            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {t('calls.shown', { count: formatCount(page.items.length) })}
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
                  {t('calls.prevPage')}
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
                  {t('calls.nextPage')}
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </>
        )}
      </QueryBoundary>

      {can(Perm.REPORTS_EXPORT) ? (
        <ExportCallsModal
          open={exporting}
          onOpenChange={setExporting}
          query={query}
          // The list's own total — the number UC-22 requires the file's row
          // count to equal. Computing a second one here is how that guarantee
          // starts looking broken.
          total={typeof total === 'number' ? total : null}
          filterSummary={filterSummary}
        />
      ) : null}
    </Page>
  )
}
