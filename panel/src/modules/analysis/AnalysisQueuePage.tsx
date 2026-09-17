/**
 * `/analysis/queue` — what is waiting and what broke (SPEC-ANALYTICS §7.5).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This is where an admin answers **"why has nothing been scored since
 * Tuesday"**. It exists in phase 1 because without it that question has no
 * answer short of opening the database — which is also why every number on it
 * is paired with the thing that explains it:
 *
 *   the stage counts        what is moving
 *   `waiting_retry`         what will fix itself, kept apart from `failed`
 *                           on purpose: one of them needs a person
 *   `not_analysable`        why calls are being skipped, by reason, so
 *                           "412 calls are waiting on the line directory" is
 *                           visible rather than silent (§2.6)
 *   the cooldowns           the first thing to look at when the queue goes
 *                           quiet — a quota that reset and a 503 read very
 *                           differently
 *   the month               spend against BOTH caps, and `priced: false`
 *                           rather than "$0.00"
 *   `recent_failures`       twenty rows, each with a way to act on it
 *
 * `enabled` is on this response too, and with the flag seeded false that is the
 * honest headline for the whole page rather than six zeroes with no explanation.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { Link } from 'react-router-dom'
import { AlertTriangle, PauseCircle, PowerOff, RotateCcw } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import {
  EM_DASH,
  formatCount,
  formatDate,
  formatDateTime,
  formatDateTimeOrDash,
  formatDuration,
  formatInstantTitle,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { Section } from '@/shared/ui/detail'
import { ProgressBar } from '@/shared/ui/ProgressBar'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  useAnalysisStatus,
  useQueueAnalysis,
  type AnalysisFailureRow,
  type AnalysisMonth,
  type AnalysisStage,
  type AnalysisStatus,
} from './api'
import {
  cooldownRoleLabel,
  failureHalfLabel,
  FAILURE_LABEL,
  STAGE_LABEL,
  STAGE_TONE,
} from './labels'
import { monthCost } from './state'

/** The six stages, in pipeline order rather than alphabetically: a reader
 *  follows a call left to right through them. */
const STAGE_ORDER: readonly AnalysisStage[] = [
  'queued',
  'transcribing',
  'scoring',
  'completed',
  'skipped',
  'failed',
]

function StageTile({ stage, count }: { stage: AnalysisStage; count: number }) {
  return (
    <Card className="p-3">
      <Badge tone={STAGE_TONE[stage]}>{t(STAGE_LABEL[stage])}</Badge>
      <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-text">
        {formatCount(count)}
      </p>
    </Card>
  )
}

/**
 * This month's spend against the caps.
 *
 * **`priced: false` never renders as a number.** A cost of zero because nobody
 * has entered a vendor price is not a free feature, and $0.00 on this page is
 * how a client concludes it is (§11.1). The CALL cap is what actually protects
 * the account until a price is typed in, so it is the bar that is drawn.
 */
function MonthCard({ month }: { month: AnalysisMonth }) {
  const cost = monthCost(month)
  const callFraction = month.cap_calls > 0 ? month.calls / month.cap_calls : 0

  return (
    <Section
      title={t('analysis.monthTitle')}
      description={t('analysis.monthFrom', { date: formatDate(month.date_from) })}
    >
      <div className="flex flex-col gap-4">
        <div>
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-xs text-text">{t('analysis.monthCalls')}</span>
            <span className="font-mono text-xs tabular-nums text-muted">
              {t('analysis.ofCap', {
                used: formatCount(month.calls),
                cap: formatCount(month.cap_calls),
              })}
            </span>
          </div>
          <ProgressBar
            fraction={callFraction}
            tone={callFraction >= 1 ? 'bad' : callFraction >= 0.8 ? 'warn' : 'accent'}
            label={t('analysis.monthCalls')}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <p className="text-2xs font-medium uppercase tracking-wide text-muted">
              {t('analysis.monthAudio')}
            </p>
            <p className="font-mono text-sm tabular-nums text-text">
              {t('analysis.minutes', { count: formatCount(month.audio_minutes) })}
            </p>
          </div>
          <div>
            <p className="text-2xs font-medium uppercase tracking-wide text-muted">
              {t('analysis.monthTokens')}
            </p>
            <p className="font-mono text-sm tabular-nums text-text">
              {formatCount(month.prompt_tokens)} / {formatCount(month.completion_tokens)}
            </p>
          </div>
          <div>
            <p className="text-2xs font-medium uppercase tracking-wide text-muted">
              {t('analysis.monthCost')}
            </p>
            {cost.text === null ? (
              <p className="text-sm text-warn">{t('analysis.monthNotPriced')}</p>
            ) : (
              <p className="font-mono text-sm tabular-nums text-text">
                {t('analysis.ofCap', { used: cost.text, cap: cost.cap ?? EM_DASH })}
              </p>
            )}
          </div>
        </div>

        {cost.text === null ? (
          <p className="text-xs text-muted">{t('analysis.monthNotPricedHint')}</p>
        ) : null}
      </div>
    </Section>
  )
}

/**
 * One recent failure, with enough to act on it.
 *
 * The retry button is `analysis:run` only and is the same mutation the detail
 * page uses, so a re-press is indistinguishable from the first press and the
 * whole module is invalidated on success — the counts above and this row agree
 * without a second request.
 */
function FailureRow({ row }: { row: AnalysisFailureRow }) {
  const can = useAuth((state) => state.can)
  const mutation = useQueueAnalysis()
  const busy = mutation.status === 'pending'

  return (
    <TR>
      <TD className="whitespace-nowrap" title={formatInstantTitle(row.started_at)}>
        <Link
          to={`/analysis/${row.call_id}`}
          className="text-muted underline-offset-2 hover:text-accent hover:underline"
        >
          {formatDateTime(row.started_at)}
        </Link>
      </TD>
      <TD>
        <span className="flex flex-col gap-0.5">
          <span className="text-sm text-text">{t(FAILURE_LABEL[row.code])}</span>
          {row.detail ? (
            <span className="max-w-[28rem] truncate font-mono text-2xs text-muted" title={row.detail}>
              {row.detail}
            </span>
          ) : null}
        </span>
      </TD>
      <TD className="whitespace-nowrap text-xs text-muted">
        {failureHalfLabel(row.stage) ?? EM_DASH}
      </TD>
      <TD className="text-end font-mono text-xs tabular-nums">{row.attempts}</TD>
      <TD className="whitespace-nowrap text-xs text-muted">
        {formatDateTimeOrDash(row.last_run_at)}
      </TD>
      <TD>
        {can(Perm.ANALYSIS_RUN) ? (
          <span className="flex flex-col items-start gap-1">
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => mutation.mutate(row.call_id)}
            >
              <RotateCcw className="size-3.5" aria-hidden />
              {busy ? t('analysis.runBusy') : t('analysis.retryButton')}
            </Button>
            {mutation.error ? (
              <span className="text-2xs text-bad">{messageForError(mutation.error)}</span>
            ) : null}
          </span>
        ) : null}
      </TD>
    </TR>
  )
}

function QueueBody({ status }: { status: AnalysisStatus }) {
  return (
    <div className="flex flex-col gap-4">
      {/* The flag, first and plainly. With `analysis.enabled` false the six
          zeroes below are correct and would otherwise read as a broken page. */}
      {!status.enabled ? (
        <Card className="flex items-center gap-3 border-warn/40 bg-warn/5 p-3">
          <PowerOff className="size-4 shrink-0 text-warn" aria-hidden />
          <div>
            <p className="text-sm font-medium text-text">{t('analysis.disabledTitle')}</p>
            <p className="text-xs text-muted">{t('analysis.queueDisabledHint')}</p>
          </div>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {STAGE_ORDER.map((stage) => (
          <StageTile key={stage} stage={stage} count={status.stages[stage]} />
        ))}
      </div>

      {/* Deliberately apart from `stages.failed`: one of these needs a person
          and the other does not (§6.2). Merging them is how 885 rate-limited
          calls stayed "permanently failed" in BonviZvonki after the quota they
          were waiting on had already reset. */}
      <Card className="flex flex-wrap items-center gap-3 p-3">
        <span className="text-xs text-muted">{t('analysis.waitingRetry')}</span>
        <span className="font-mono text-lg font-semibold tabular-nums text-text">
          {formatCount(status.waiting_retry)}
        </span>
        <span className="text-xs text-muted">{t('analysis.waitingRetryHint')}</span>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        <Section
          title={t('analysis.notAnalysableTitle')}
          description={t('analysis.notAnalysableHint')}
        >
          {status.not_analysable.length === 0 ? (
            <p className="text-sm text-muted">{t('analysis.notAnalysableEmpty')}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {status.not_analysable.map((reason) => (
                <li key={reason.code} className="flex items-baseline justify-between gap-3">
                  <span className="text-sm text-text">{t(FAILURE_LABEL[reason.code])}</span>
                  <span className="font-mono text-sm tabular-nums text-muted">
                    {formatCount(reason.calls)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title={t('analysis.cooldownTitle')} description={t('analysis.cooldownHint')}>
          {status.cooldowns.length === 0 ? (
            // The normal state, and it should read as good news rather than as
            // the same grey box every empty list shows.
            <p className="text-sm text-muted">{t('analysis.cooldownEmpty')}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {status.cooldowns.map((cooldown) => (
                <li
                  key={cooldown.role}
                  className="rounded-md border border-warn/30 bg-warn/5 p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <PauseCircle className="size-4 shrink-0 text-warn" aria-hidden />
                    <span className="text-sm font-medium text-text">
                      {cooldownRoleLabel(cooldown.role)}
                    </span>
                    <Badge tone="warn">{t(FAILURE_LABEL[cooldown.reason_code])}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    {t('analysis.cooldownLeft', {
                      time: formatDuration(cooldown.seconds_left),
                      until: formatDateTime(cooldown.until_at),
                    })}
                  </p>
                  {cooldown.detail ? (
                    <p className="mt-1 font-mono text-2xs text-muted">{cooldown.detail}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <MonthCard month={status.month} />

      <Section title={t('analysis.failuresTitle')} description={t('analysis.failuresHint')}>
        {status.recent_failures.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted">
            <AlertTriangle className="size-4 text-good" aria-hidden />
            {t('analysis.failuresEmpty')}
          </p>
        ) : (
          <TableWrap>
            <Table>
              <THead>
                <tr>
                  <TH>{t('analysis.colTime')}</TH>
                  <TH>{t('analysis.colReason')}</TH>
                  <TH>{t('analysis.colHalf')}</TH>
                  <TH className="text-end">{t('analysis.colAttempts')}</TH>
                  <TH>{t('analysis.colLastRun')}</TH>
                  <TH>{t('analysis.colAction')}</TH>
                </tr>
              </THead>
              <TBody>
                {status.recent_failures.map((row) => (
                  <FailureRow key={row.call_id} row={row} />
                ))}
              </TBody>
            </Table>
          </TableWrap>
        )}
      </Section>
    </div>
  )
}

export function AnalysisQueuePage() {
  const statusQuery = useAnalysisStatus()

  return (
    <Page>
      <PageHeader
        title={t('page.analysisQueue')}
        description={t('analysis.queueSubtitle')}
        actions={
          <Link
            to="/analysis"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            {t('analysis.openList')}
          </Link>
        }
      />
      {/* No `isEmpty`: this page is never empty. Six zeroes and a flag that is
          off IS the answer somebody came here for, and replacing it with a
          generic "nothing here" box would hide exactly that. */}
      <QueryBoundary query={statusQuery} skeletonRows={6}>
        {(status) => <QueueBody status={status} />}
      </QueryBoundary>
    </Page>
  )
}
