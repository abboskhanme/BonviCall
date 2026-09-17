/**
 * `/clients/:key` — one customer's card.
 *
 * Ported from BonviZvonki `web/src/modules/clients/ClientDetailPage.tsx`.
 *
 * ⚠️ The card is asked with the SAME filter the list was asked with. If the
 * two drift, a row reading "12 calls" opens onto a different number and the
 * reader has no way to know which to believe — the tool built to prove a
 * figure is then what makes it doubtful.
 *
 * ⚠️ An empty period is NOT an unknown customer. The server answers with zeros
 * and the card opens; the table below offers "whole history" as the way out.
 * Narrowing the dates must never read as "this customer does not exist".
 *
 * ═══ SALES SEAM ═══════════════════════════════════════════════════════════
 * BonviZvonki's card carries a SECOND half: a merged calls-and-sales timeline,
 * a sales summary strip (count, amount, suspicious, not-checkable) and a
 * partner-exclusion control, all fed by `GET /clients/{key}/sales`. That
 * endpoint is gated **separately** on `sales:read` and explicitly NOT inherited
 * from the right to open this card, because the list is a check carried out ON
 * a salesperson and they must not see their own deal flagged as suspicious.
 *
 * None of it is ported: the `sales` module is being ported separately and
 * nothing here reads a `sales*` table. The seam is marked below, where the
 * strip and the extra timeline rows attach.
 * ═════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Clock,
  PhoneIncoming,
  PhoneMissed,
  PhoneOutgoing,
  Star,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { t } from '@/shared/i18n'
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
import { Section } from '@/shared/ui/detail'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  PAGE_SIZE,
  useClient,
  useClientCalls,
  type ClientCall,
  type ClientCallsPage,
  type ClientDetail,
  type ClientScope,
} from './api'

const PARAM_SCOPE = 'scope'
const PARAM_DATE_FROM = 'date_from'
const PARAM_DATE_TO = 'date_to'

function Stat({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: LucideIcon
  label: string
  value: string
  hint: string
  tone?: 'bad' | 'good'
}) {
  return (
    <Card className="flex items-start gap-3 p-4">
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-md',
          tone === 'bad' ? 'bg-bad/10 text-bad' : 'bg-surface-2 text-muted',
        )}
      >
        <Icon className="size-4" aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block text-2xs font-medium uppercase tracking-wide text-muted">
          {label}
        </span>
        <span
          className={cn(
            'block text-lg font-semibold tabular-nums text-text',
            tone === 'bad' && 'text-bad',
          )}
        >
          {value}
        </span>
        <span className="block text-2xs text-muted">{hint}</span>
      </span>
    </Card>
  )
}

/**
 * The direction cell.
 *
 * ⚠️ Only INBOUND-and-unanswered is red. An outgoing call the customer did not
 * pick up is not the employee's fault, and colouring it the same way blames
 * them for it — measured over a week, the two happen about equally often (983
 * against 1047), so the distinction is not a rare case.
 */
function DirectionCell({ call }: { call: ClientCall }) {
  const inbound = call.direction === 'incoming'
  const answered = call.disposition === 'answered'
  const Icon = !answered && inbound ? PhoneMissed : inbound ? PhoneIncoming : PhoneOutgoing
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <Icon
        className={cn('size-3.5 shrink-0', !answered && inbound ? 'text-bad' : 'text-muted')}
        aria-hidden
      />
      <span>
        {t(inbound ? 'clients.dirFromClient' : 'clients.dirToClient')}
        {answered ? null : (
          <span
            className={cn('block text-2xs', inbound ? 'text-bad' : 'text-muted')}
          >
            {t(inbound ? 'clients.dirNoAnswer' : 'clients.dirNotPicked')}
          </span>
        )}
      </span>
    </span>
  )
}

function CallRows({ page }: { page: ClientCallsPage }) {
  const navigate = useNavigate()
  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            <TH>{t('clients.colDate')}</TH>
            <TH>{t('clients.colDirection')}</TH>
            <TH>{t('clients.colAgent')}</TH>
            <TH className="text-end">{t('clients.colDuration')}</TH>
            <TH className="text-end">{t('clients.colScoreShort')}</TH>
            <TH className="text-end">{t('clients.colStatus')}</TH>
          </tr>
        </THead>
        <TBody>
          {page.items.map((call) => (
            <TR key={call.id} interactive onClick={() => navigate(`/calls/${call.id}`)}>
              <TD className="whitespace-nowrap" title={formatInstantTitle(call.started_at)}>
                <Link
                  to={`/calls/${call.id}`}
                  className="text-muted underline-offset-2 hover:text-accent hover:underline"
                  onClick={(event) => event.stopPropagation()}
                >
                  {formatDate(call.started_at)}
                </Link>
                <span className="block text-2xs text-muted">
                  {formatTime(call.started_at)}
                </span>
              </TD>
              <TD>
                <DirectionCell call={call} />
              </TD>
              <TD className="max-w-[12rem] truncate">{call.agent_name}</TD>
              <TD className="text-end font-mono tabular-nums">
                {formatDuration(call.duration_sec)}
              </TD>
              <TD className="text-end font-mono tabular-nums">
                {call.score === null ? (
                  <span className="text-muted">{EM_DASH}</span>
                ) : (
                  call.score
                )}
              </TD>
              <TD className="whitespace-nowrap text-end">
                {call.red_flag_count > 0 ? (
                  <Badge tone="bad">
                    {t('clients.redFlags', { count: call.red_flag_count })}
                  </Badge>
                ) : null}
                {call.needs_review ? (
                  <Badge tone="warn" className="ms-1">
                    {t('clients.needsReview')}
                  </Badge>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  )
}

export function ClientDetailPage() {
  const { key } = useParams<{ key: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const scope = (searchParams.get(PARAM_SCOPE) ?? undefined) as ClientScope | undefined
  const dateFrom = searchParams.get(PARAM_DATE_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_DATE_TO) ?? undefined
  const [trail, setTrail] = useState<string[]>([])
  const [cursor, setCursor] = useState<string | undefined>(undefined)

  /** The filter, built ONCE and handed to both queries. */
  const filter = {
    ...(scope ? { scope } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  }

  const clientQuery = useClient(key, filter)
  const callsQuery = useClientCalls(key, {
    ...filter,
    limit: PAGE_SIZE,
    ...(cursor ? { cursor } : {}),
    with_total: cursor === undefined,
  })

  const bounded = Boolean(dateFrom || dateTo)

  function clearDates() {
    const next = new URLSearchParams(searchParams)
    next.delete(PARAM_DATE_FROM)
    next.delete(PARAM_DATE_TO)
    setTrail([])
    setCursor(undefined)
    setSearchParams(next, { replace: true })
  }

  return (
    <QueryBoundary query={clientQuery} skeletonRows={6}>
      {(detail: ClientDetail) => {
        const client = detail.client
        return (
          <Page>
            <PageHeader
              title={client.name ?? formatPhone(client.phone) ?? client.phone_key}
              description={
                [
                  client.code ?? null,
                  client.name ? (formatPhone(client.phone) ?? client.phone_key) : null,
                ]
                  .filter(Boolean)
                  .join(' · ') || undefined
              }
              actions={
                <Button variant="secondary" size="sm" onClick={() => history.back()}>
                  <ArrowLeft className="size-4" aria-hidden />
                  {t('clients.back')}
                </Button>
              }
            />

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Stat
                icon={Users}
                label={t('clients.colCalls')}
                value={formatCount(client.calls_total)}
                hint={t('clients.inOut', {
                  inbound: formatCount(client.inbound),
                  outbound: formatCount(client.outbound),
                })}
              />
              {/* ⚠️ "Xodim ko'tarmadi" — incoming and unanswered only. The
                  outgoing half is the customer being busy and is deliberately
                  not added to it. */}
              <Stat
                icon={PhoneMissed}
                label={t('clients.colMissed')}
                value={formatCount(client.missed)}
                hint={t('clients.missedHint')}
                tone={client.missed > 0 ? 'bad' : 'good'}
              />
              <Stat
                icon={Clock}
                label={t('clients.colTalk')}
                value={formatDuration(client.talk_seconds)}
                hint={t('clients.talkHint')}
              />
              <Stat
                icon={Star}
                label={t('clients.colScore')}
                value={
                  client.avg_score === null ? EM_DASH : String(Math.round(client.avg_score))
                }
                hint={t('clients.scoredOf', {
                  total: formatCount(client.calls_total),
                  scored: formatCount(client.scored),
                })}
              />
            </div>

            {/* Hidden entirely rather than rendered empty: an empty card asks
                the reader to work out why it is there. */}
            {detail.agents.length > 0 ? (
              <Section title={t('clients.agentsTitle')} description={t('clients.agentsHint')}>
                <div className="flex flex-wrap gap-2">
                  {detail.agents.map((agent) => (
                    <Link
                      key={agent.agent_id}
                      to={`/agents/${agent.agent_id}`}
                      className={cn(
                        'flex items-center gap-2 rounded-md border border-border',
                        'bg-surface-2 px-3 py-1.5 text-sm text-text',
                        'transition-colors hover:border-accent hover:text-accent',
                      )}
                    >
                      <span className="truncate">{agent.full_name}</span>
                      <span className="text-2xs text-muted">
                        {t('clients.agentCalls', { count: formatCount(agent.calls) })}
                      </span>
                    </Link>
                  ))}
                </div>
              </Section>
            ) : null}

            {/*
              SALES SEAM — the sales summary strip goes here, above the table,
              and the timeline below merges sale rows into it. Both wait on the
              `sales` module and on `GET /clients/{key}/sales`, which carries
              its own `sales:read` gate rather than inheriting this page's.
            */}

            <Section
              title={t('clients.callsTitle')}
              description={t('clients.callsHint')}
              actions={
                typeof callsQuery.data?.total === 'number' ? (
                  <span className="text-xs tabular-nums text-muted">
                    {formatCount(callsQuery.data.total)}
                  </span>
                ) : null
              }
            >
              <QueryBoundary
                query={callsQuery}
                isEmpty={(page) => page.items.length === 0}
                emptyTitle={
                  bounded ? t('clients.emptyPeriod') : t('clients.emptyAllCalls')
                }
                emptyHint={bounded ? t('clients.emptyPeriodHint') : undefined}
                emptyAction={
                  bounded ? (
                    <Button variant="secondary" size="sm" onClick={clearDates}>
                      {t('clients.clearDates')}
                    </Button>
                  ) : undefined
                }
                skeletonRows={6}
              >
                {(page) => (
                  <div className="space-y-3">
                    <CallRows page={page} />
                    <div className="flex items-center justify-end gap-2">
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
                        {t('clients.prevPage')}
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
                        {t('clients.nextPage')}
                        <ChevronRight className="size-4" aria-hidden />
                      </Button>
                    </div>
                  </div>
                )}
              </QueryBoundary>
            </Section>
          </Page>
        )
      }}
    </QueryBoundary>
  )
}
