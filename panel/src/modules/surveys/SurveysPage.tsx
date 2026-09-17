/**
 * `/surveys` — what customers said about the people who served them.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **The average is withheld until there are enough answers, and it is `null`
 * rather than `0` while it is withheld.** The threshold is an admin setting,
 * so this page never writes a number for it — it reads `min_responses` out of
 * the response. A hard-coded "/5" while the admin had set 8 is the exact
 * defect the source's own comment records.
 *
 * **A salesperson sees their summary and never the individual ratings.** One
 * Telegram group is one customer, so a single visible row tells them which
 * customer wrote it — and the anonymity was promised to that customer in their
 * own chat. The server enforces it; this page explains it, because an empty
 * list with no explanation reads as "nobody has ever rated you".
 *
 * **The misconduct labels come from the server**, never from a list in this
 * module, so a new criterion appears without a panel deploy.
 *
 * Access: `analysis:read` (admin, manager) or `calls:read:own` (a salesperson,
 * narrowed by the server to their own agent). The route guard and nav entry
 * are in `router.tsx` and `AppShell.tsx` and are NOT edited by this port — the
 * wiring is listed in the hand-off report.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useMemo, useState } from 'react'
import { EyeOff, Flag, Info, MessageSquare, Star, TrendingUp } from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount, formatDate } from '@/shared/lib/format'
import { widthClass } from '@/shared/lib/widthClass'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { DateFilter, FilterField, SearchFilter, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  csatTone,
  DEFAULT_PERIOD,
  isForbidden,
  LOW_CSAT_MAX,
  PERIOD_LABEL,
  PERIODS,
  remaining,
  useFeedback,
  useRedFlagLabels,
  type Feedback,
  type FeedbackItem,
  type Period,
} from './api'
import { CommentModal } from './CommentModal'
import { RedFlagChips } from './RedFlagChips'
import { Stars } from './Stars'

type ListFilter = 'all' | 'comments' | 'low' | 'flagged'

export function SurveysPage() {
  const { can } = useAuth()
  // Fleet-wide reader, or a salesperson narrowed to themselves by the SERVER.
  // The panel never re-implements the narrowing; it only hides a filter that
  // would do nothing, which is presentation rather than access control.
  const fleetWide = can(Perm.ANALYSIS_READ)

  const [days, setDays] = useState<Period>(DEFAULT_PERIOD)
  const [dateFrom, setDateFrom] = useState<string | undefined>(undefined)
  const [dateTo, setDateTo] = useState<string | undefined>(undefined)
  const [agentId, setAgentId] = useState('')
  const [search, setSearch] = useState<string | undefined>(undefined)
  const [filter, setFilter] = useState<ListFilter>('all')
  const [opened, setOpened] = useState<FeedbackItem | null>(null)

  const report = useFeedback({
    days,
    date_from: dateFrom,
    date_to: dateTo,
    agent_id: fleetWide && agentId ? agentId : undefined,
    search: search?.trim() || undefined,
  })

  const agents = useAgentDirectory(fleetWide && can(Perm.AGENTS_READ))
  const flagLabel = useRedFlagLabels()

  const title = fleetWide ? t('surveys.title') : t('surveys.myTitle')

  // ── The section is closed to this caller by the access setting ──────────
  // A 403 here is a configuration answer, not a failure, so it gets its own
  // screen instead of the generic error card.
  if (isForbidden(report.error)) {
    return (
      <Page>
        <PageHeader title={title} />
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <EyeOff className="size-8 text-muted" aria-hidden />
          <p className="text-sm font-medium text-text">{t('surveys.forbidden')}</p>
          <p className="max-w-md text-xs leading-relaxed text-muted">
            {t('surveys.forbiddenHint')}
          </p>
        </Card>
      </Page>
    )
  }

  return (
    <Page>
      <PageHeader
        title={title}
        description={t('surveys.subtitle', {
          count: formatCount(report.data?.count ?? 0),
          days,
        })}
        actions={
          <div className="flex flex-wrap items-end justify-end gap-2">
            <div className="flex items-center gap-1">
              {PERIODS.map((period) => (
                <Button
                  key={period}
                  size="sm"
                  variant={period === days && !dateFrom && !dateTo ? 'primary' : 'ghost'}
                  onClick={() => {
                    setDays(period)
                    // An explicit range wins on the server, so pressing a
                    // one-click window has to clear it or the button appears
                    // to do nothing.
                    setDateFrom(undefined)
                    setDateTo(undefined)
                  }}
                >
                  {t(PERIOD_LABEL[period])}
                </Button>
              ))}
            </div>
            <DateFilter
              label={t('surveys.dateFrom')}
              hint={t('surveys.dateFrom')}
              pickLabel={t('surveys.dateFrom')}
              clearLabel={t('groups.clearSearch')}
              value={dateFrom}
              max={dateTo}
              onChange={(value) => setDateFrom(value ?? undefined)}
            />
            <DateFilter
              label={t('surveys.dateTo')}
              hint={t('surveys.dateTo')}
              pickLabel={t('surveys.dateTo')}
              clearLabel={t('groups.clearSearch')}
              value={dateTo}
              min={dateFrom}
              onChange={(value) => setDateTo(value ?? undefined)}
            />
            {fleetWide ? (
              <>
                <FilterField label={t('surveys.agentFilter')}>
                  <select
                    className={SELECT_CLASS}
                    value={agentId}
                    onChange={(event) => setAgentId(event.target.value)}
                  >
                    <option value="">{t('surveys.allAgents')}</option>
                    {(agents.data?.items ?? []).map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.full_name}
                      </option>
                    ))}
                  </select>
                </FilterField>
                <SearchFilter
                  label={t('surveys.searchLabel')}
                  placeholder={t('surveys.searchPlaceholder')}
                  value={search}
                  onCommit={(value) => setSearch(value ?? undefined)}
                  clearLabel={t('groups.clearSearch')}
                  className="w-56"
                />
              </>
            ) : null}
          </div>
        }
      />

      <QueryBoundary query={report} skeletonRows={6}>
        {(data) => (
          <>
            <Summary data={data} fleetWide={fleetWide} />

            {/* ⚠️ Rows withheld is NOT the same as no rows. Said in words, or
                an employee reads an empty list as "nobody has rated me". */}
            {data.items_withheld ? (
              <div className="flex items-start gap-2.5 rounded-md border border-border bg-surface-2 px-3 py-2.5">
                <Info className="mt-px size-4 shrink-0 text-muted" aria-hidden />
                <p className="text-xs leading-relaxed text-muted">
                  {t('surveys.itemsWithheld')}
                </p>
              </div>
            ) : null}

            {/* With the rows withheld the list card would repeat the banner
                above it word for word, and its filters and "open a card" hint
                would describe rows that are not there. The distribution is
                the whole of what this reader gets, so it gets the width. */}
            {data.items_withheld ? (
              <Distribution data={data} />
            ) : (
              <div className="grid gap-4 xl:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
                <Distribution data={data} />
                <FeedbackList
                  data={data}
                  filter={filter}
                  onFilter={setFilter}
                  showAgent={fleetWide}
                  flagLabel={flagLabel}
                  onOpen={setOpened}
                  searching={Boolean(search?.trim())}
                  query={search?.trim() ?? ''}
                />
              </div>
            )}
          </>
        )}
      </QueryBoundary>

      <CommentModal
        item={opened}
        showAgent={fleetWide}
        flagLabel={flagLabel}
        onClose={() => setOpened(null)}
      />
    </Page>
  )
}

function Summary({ data, fleetWide }: { data: Feedback; fleetWide: boolean }) {
  const left = remaining(data)
  const withComments = data.items.filter((item) => item.comment).length

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Card className="p-4">
        <Head icon={Star} tone="warn" label={t('surveys.average')} />
        {data.ready && data.average !== null ? (
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span className="text-2xl font-semibold tabular-nums leading-none text-text">
              {data.average.toFixed(2)}
            </span>
            <Stars value={data.average} />
          </div>
        ) : (
          <>
            {/* ⚠️ A count out of the threshold, not an em dash. "—" reads as
                "this is broken"; "3 / 5" reads as "it is working and not
                ready", which is the truth. */}
            <div className="flex flex-wrap items-center gap-2">
              {data.count > 0 ? (
                <span className="text-2xl font-semibold tabular-nums leading-none text-text">
                  {data.count}
                  <span className="text-base font-medium text-muted">
                    {' / '}
                    {data.min_responses}
                  </span>
                </span>
              ) : (
                <span className="text-2xl font-semibold leading-none text-muted">0</span>
              )}
              <Badge tone="warn">
                {t('surveys.collecting', { count: data.count, min: data.min_responses })}
              </Badge>
            </div>
            <p className="mt-2 text-2xs leading-relaxed text-muted">
              {left !== null && left > 0
                ? t('surveys.notReadyRemaining', { count: left, min: data.min_responses })
                : t('surveys.notReadyHint')}
            </p>
          </>
        )}
      </Card>

      <Card className="p-4">
        <Head icon={MessageSquare} label={t('surveys.responses')} />
        <span className="text-2xl font-semibold tabular-nums leading-none text-text">
          {formatCount(data.count)}
        </span>
        {fleetWide ? (
          <p className="mt-2 text-2xs text-muted">
            {t('surveys.withComments', { count: withComments })}
          </p>
        ) : null}
      </Card>

      <Card className="p-4">
        <Head icon={TrendingUp} tone="good" label={t('surveys.responseRate')} />
        <span className="text-2xl font-semibold tabular-nums leading-none text-text">
          {/* ⚠️ Null is not 0 %. Nothing has been SENT in this deployment —
              there is no bot — so there is no denominator, and "0 %" would
              read as "every customer ignored us". */}
          {data.response_rate !== null ? `${data.response_rate}%` : EM_DASH}
        </span>
        <p className="mt-2 text-2xs leading-relaxed text-muted">
          {data.response_rate !== null
            ? t('surveys.responseRateHint')
            : t('surveys.responseRateNone')}
        </p>
      </Card>
    </div>
  )
}

function Head({
  icon: Icon,
  label,
  tone = 'accent',
}: {
  icon: typeof Star
  label: string
  tone?: 'accent' | 'good' | 'warn'
}) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <Icon
        className={cn(
          'size-4',
          tone === 'accent' && 'text-accent',
          tone === 'good' && 'text-good',
          tone === 'warn' && 'text-warn',
        )}
        aria-hidden
      />
      <span className="text-2xs font-medium uppercase tracking-wide text-muted">{label}</span>
    </div>
  )
}

function Distribution({ data }: { data: Feedback }) {
  return (
    <Card className="p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-text">{t('surveys.distribution')}</h2>
        <p className="mt-0.5 text-xs text-muted">{t('surveys.anonymous')}</p>
      </div>
      {data.count === 0 ? (
        <p className="rounded-md bg-surface-2 px-3 py-2.5 text-2xs text-muted">
          {t('surveys.emptyRange')}
        </p>
      ) : (
        <div className="space-y-2.5">
          {[5, 4, 3, 2, 1].map((star) => {
            const count = data.distribution[String(star)] ?? 0
            const percent = data.count > 0 ? Math.round((count / data.count) * 100) : 0
            return (
              <div key={star} className="flex items-center gap-3">
                <span className="flex w-8 shrink-0 items-center gap-0.5 text-2xs font-medium tabular-nums text-muted">
                  {star}
                  <Star className="size-3 fill-warn text-warn" aria-hidden />
                </span>
                {/* A token-coloured bar sized by a Tailwind width class. An
                    arbitrary computed width would need `style={{ width }}`,
                    which is forbidden (§11) — `widthClass` is the panel's
                    existing answer and rounds to the nearest step. */}
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <span
                    className={cn(
                      'block h-full rounded-full',
                      star >= 4 ? 'bg-good' : star === 3 ? 'bg-warn' : 'bg-bad',
                      widthClass(percent / 100),
                    )}
                  />
                </span>
                <span className="w-14 shrink-0 text-end text-2xs tabular-nums text-muted">
                  {count}
                  <span className="ms-1 opacity-60">{percent}%</span>
                </span>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

function FeedbackList({
  data,
  filter,
  onFilter,
  showAgent,
  flagLabel,
  onOpen,
  searching,
  query,
}: {
  data: Feedback
  filter: ListFilter
  onFilter: (value: ListFilter) => void
  showAgent: boolean
  flagLabel: (key: string) => string
  onOpen: (item: FeedbackItem) => void
  searching: boolean
  query: string
}) {
  const flagged = useMemo(
    () => data.items.filter((item) => item.red_flags.length > 0).length,
    [data.items],
  )

  const visible = useMemo(() => {
    if (filter === 'comments') return data.items.filter((item) => item.comment)
    if (filter === 'low') return data.items.filter((item) => item.csat <= LOW_CSAT_MAX)
    if (filter === 'flagged') return data.items.filter((item) => item.red_flags.length > 0)
    return data.items
  }, [data.items, filter])

  const tabs: { value: ListFilter; label: string; show: boolean }[] = [
    { value: 'all', label: t('surveys.filterAll'), show: true },
    { value: 'comments', label: t('surveys.filterComments'), show: true },
    { value: 'low', label: t('surveys.filterLow'), show: true },
    // A filter that would always return nothing is not offered.
    { value: 'flagged', label: t('surveys.filterFlagged'), show: flagged > 0 },
  ]

  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-text">{t('surveys.feedbackTitle')}</h2>
          <p className="mt-0.5 text-xs text-muted">{t('surveys.feedbackHint')}</p>
        </div>
        {data.items.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1">
            {tabs
              .filter((tab) => tab.show)
              .map((tab) => (
                <Button
                  key={tab.value}
                  size="sm"
                  variant={filter === tab.value ? 'primary' : 'ghost'}
                  onClick={() => onFilter(tab.value)}
                >
                  {tab.label}
                </Button>
              ))}
          </div>
        ) : null}
      </div>

      {/* Three different empty sentences, because they are three different
          situations and a reader can act on only one of them (SPEC §5.3). */}
      {data.items.length === 0 ? (
        <p className="rounded-md bg-surface-2 px-3 py-2.5 text-2xs leading-relaxed text-muted">
          {searching ? t('surveys.searchEmptyHint') : t('surveys.emptyRange')}
        </p>
      ) : visible.length === 0 ? (
        <p className="rounded-md bg-surface-2 px-3 py-2.5 text-2xs text-muted">
          {searching ? t('surveys.searchEmpty', { query }) : t('surveys.emptyFilter')}
        </p>
      ) : (
        <div className="grid gap-2 2xl:grid-cols-2">
          {visible.map((item) => (
            <FeedbackCard
              key={item.id}
              item={item}
              showAgent={showAgent}
              flagLabel={flagLabel}
              onOpen={() => onOpen(item)}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

const RESOLUTION_TONE = { yes: 'good', partial: 'warn', no: 'bad' } as const
const RESOLUTION_LABEL = {
  yes: 'surveys.resolution.yes',
  partial: 'surveys.resolution.partial',
  no: 'surveys.resolution.no',
} as const

function FeedbackCard({
  item,
  showAgent,
  flagLabel,
  onOpen,
}: {
  item: FeedbackItem
  showAgent: boolean
  flagLabel: (key: string) => string
  onOpen: () => void
}) {
  const tone = csatTone(item.csat)
  const resolution = item.resolution as keyof typeof RESOLUTION_LABEL | null

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'flex w-full flex-col gap-2 rounded-md border p-3 text-start transition-colors',
        // A rating carrying a complaint looks different from a merely low one.
        item.red_flags.length > 0
          ? 'border-bad/30 bg-bad/[0.05] hover:bg-bad/10'
          : 'border-border bg-surface hover:bg-surface-2',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-semibold',
            tone === 'good' && 'bg-good/10 text-good',
            tone === 'warn' && 'bg-warn/10 text-warn',
            tone === 'bad' && 'bg-bad/10 text-bad',
          )}
        >
          <Star className="size-3 fill-current" aria-hidden />
          <span className="tabular-nums">{item.csat}</span>
        </span>

        {resolution ? (
          <Badge tone={RESOLUTION_TONE[resolution]}>{t(RESOLUTION_LABEL[resolution])}</Badge>
        ) : null}

        {item.red_flags.length > 0 ? (
          <Badge tone="bad">
            <Flag className="me-1 size-3 fill-current" aria-hidden />
            <span className="tabular-nums">{item.red_flags.length}</span>
          </Badge>
        ) : null}

        <span className="ms-auto shrink-0 text-2xs tabular-nums text-muted">
          {formatDate(item.responded_at)}
        </span>
      </div>

      <RedFlagChips keys={item.red_flags} flagLabel={flagLabel} max={3} />

      {item.comment ? (
        <p className="line-clamp-2 text-xs leading-relaxed text-text">{item.comment}</p>
      ) : (
        <p className="text-xs italic leading-relaxed text-muted">{t('surveys.noComment')}</p>
      )}

      {showAgent ? (
        <span className="truncate text-2xs font-medium text-muted">{item.agent_name}</span>
      ) : null}
    </button>
  )
}
