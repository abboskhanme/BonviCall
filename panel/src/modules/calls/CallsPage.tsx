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
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Download, PhoneIncoming, PhoneOutgoing } from 'lucide-react'

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
import { EnumFilter, FilterField, SELECT_CLASS, TextFilter } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { useAgentDirectory } from '@/modules/agents/api'

import {
  useCallsPage,
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  type Call,
  type CallListQuery,
  type CallPage,
} from './api'
import {
  audioState,
  audioStateLabel,
  audioStateTone,
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
const PARAM_REMOTE = 'remote_number'
const PARAM_Q = 'q'
const PARAM_LIMIT = 'limit'
const PARAM_CURSOR = 'cursor'

/** Every filter parameter, so "clear" and "is anything filtered" cannot miss
 *  one — the bug where a reset button leaves a hidden filter behind. */
const FILTER_PARAMS = [
  PARAM_AGENT,
  PARAM_AUDIO,
  PARAM_DIRECTION,
  PARAM_DISPOSITION,
  PARAM_CALL_TYPE,
  PARAM_DATE_FROM,
  PARAM_DATE_TO,
  PARAM_REMOTE,
  PARAM_Q,
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

function parseLimit(raw: string | null): number {
  const value = Number(raw)
  return PAGE_SIZES.includes(value) ? value : DEFAULT_PAGE_SIZE
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
            {/* The list is ordered by `received_at`, not by `started_at`
                (SPEC §3.12: devices lie about time, and the server's receipt
                time is what orders the page). Showing only the device's clock
                while sorting by the server's makes a correctly ordered list
                look shuffled — and it hides the skew, which on a phone with a
                wrong date is days. Both columns, so the order is explainable. */}
            <TH title={t('calls.colReceivedHint')}>{t('calls.colReceived')}</TH>
            <TH>{t('calls.colDirection')}</TH>
            <TH>{t('calls.colRemote')}</TH>
            {showAgent ? <TH>{t('calls.colAgent')}</TH> : null}
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
                <TD>
                  <DirectionCell call={call} />
                </TD>
                <TD>
                  <span className="font-mono">{phone ?? t('calls.numberWithheld')}</span>
                  {call.contact_name ? (
                    <span className="ms-2 text-xs text-muted">{call.contact_name}</span>
                  ) : null}
                </TD>
                {/* `agent_name` is resolved server-side (SPEC §4.7): looking
                    a name up per row in the browser is the N+1 problem
                    relocated to the client. */}
                {showAgent ? <TD className="whitespace-nowrap">{call.agent_name}</TD> : null}
                <TD>
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
  const callType = parseEnum(searchParams.get(PARAM_CALL_TYPE), CALL_TYPE_LABEL)
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const remoteNumber = searchParams.get(PARAM_REMOTE) ?? undefined
  const nameQuery = searchParams.get(PARAM_Q) ?? undefined
  const limit = parseLimit(searchParams.get(PARAM_LIMIT))
  const cursor = searchParams.get(PARAM_CURSOR) ?? undefined

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

  const query: CallListQuery = {
    limit,
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
    ...(remoteNumber ? { remote_number: remoteNumber } : {}),
    ...(nameQuery ? { q: nameQuery } : {}),
    // SPEC §4.0: a COUNT(*) over a filtered 500k table is affordable once per
    // filter change and not once per page, so only the first page asks.
    with_total: cursor === undefined,
  }

  const callsQuery = useCallsPage(query)
  // Only the filter's option list needs the roster now that `agent_name`
  // arrives with the row. A `sales` user holds neither the permission nor the
  // filter, so nothing is requested for them.
  const agentsQuery = useAgentDirectory(showAgent && can(Perm.AGENTS_READ))

  const filtered = FILTER_PARAMS.some((param) => searchParams.get(param) !== null)

  function applyFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    // Any filter change invalidates every cursor taken under the old filter.
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

  const total = callsQuery.data?.total

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
    remoteNumber
      ? t('calls.exportFilterOne', { field: t('calls.filterRemoteNumber'), value: remoteNumber })
      : null,
    nameQuery
      ? t('calls.exportFilterOne', { field: t('calls.filterContact'), value: nameQuery })
      : null,
  ].filter((line): line is string => line !== null)

  return (
    <Page>
      <PageHeader
        title={t('page.calls')}
        description={showAgent ? undefined : t('calls.ownScopeNote')}
        actions={
          can(Perm.REPORTS_EXPORT) ? (
            <Button variant="secondary" size="sm" onClick={() => setExporting(true)}>
              <Download className="size-4" aria-hidden />
              {t('calls.export')}
            </Button>
          ) : undefined
        }
      />

      <Card className="flex flex-wrap items-end gap-3 p-3">
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
          labels={CALL_TYPE_LABEL}
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
            A native date input speaks the browser's locale and sends
            `yyyy-mm-dd`, which is exactly what the server parses. */}
        <FilterField label={t('calls.filterDateFrom')}>
          <input
            type="date"
            className={SELECT_CLASS}
            value={dateFrom ?? ''}
            max={dateTo}
            onChange={(event) => applyFilter(PARAM_DATE_FROM, event.target.value || null)}
          />
        </FilterField>
        <FilterField label={t('calls.filterDateTo')}>
          <input
            type="date"
            className={SELECT_CLASS}
            value={dateTo ?? ''}
            min={dateFrom}
            onChange={(event) => applyFilter(PARAM_DATE_TO, event.target.value || null)}
          />
        </FilterField>

        <TextFilter
          label={t('calls.filterRemoteNumber')}
          placeholder={t('calls.filterRemoteNumberHint')}
          value={remoteNumber}
          onCommit={(value) => applyFilter(PARAM_REMOTE, value)}
        />
        <TextFilter
          label={t('calls.filterContact')}
          placeholder={t('calls.filterContactHint')}
          value={nameQuery}
          onCommit={(value) => applyFilter(PARAM_Q, value)}
        />

        <FilterField label={t('calls.pageSize')}>
          <select
            className={SELECT_CLASS}
            value={String(limit)}
            onChange={(event) => applyFilter(PARAM_LIMIT, event.target.value)}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </FilterField>

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
            {t('calls.filterReset')}
          </Button>
        ) : null}

        <span className="ms-auto text-xs text-muted">
          {typeof total === 'number' ? t('calls.total', { count: formatCount(total) }) : EM_DASH}
        </span>
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
