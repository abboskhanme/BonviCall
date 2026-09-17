/**
 * `/analysis/:callId` — one call's analysis (SPEC-ANALYTICS §7.4).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Which of the seven states this page is in is decided by `analysisView()`,
 * and that function's table is an ORDERED precedence list.** The first two rows
 * overlap with every row below them, so a reader who takes the table as an
 * unordered set renders a "Tahlil qilish" button on a call whose feature flag
 * is off — a button that answers 409 `analysis_disabled` every time it is
 * pressed. The rule lives in `./state.ts` with its own test rather than as a
 * chain of ternaries in this file.
 *
 * `enabled` arrives inside this one response on purpose (§6.2): deciding what
 * to render must not cost a second round trip to `/analysis/status` to learn a
 * boolean.
 *
 * The call's own facts — when, who, which number, how long — are carried in the
 * same response and rendered at the top, so a reader is never sent to the calls
 * section to find out which conversation they are looking at. The analysis is a
 * section of its own (§7); nothing in `modules/calls` is touched by this work.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Loader2,
  Play,
  RotateCcw,
} from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { Page, PageHeader } from '@/shared/layout/Page'
import {
  EM_DASH,
  formatCount,
  formatDateTime,
  formatDateTimeOrDash,
  formatDuration,
  formatInstantTitle,
  formatPhone,
} from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { Field, FieldGrid, Section } from '@/shared/ui/detail'
import { ProgressBar } from '@/shared/ui/ProgressBar'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  useCallAnalysis,
  useQueueAnalysis,
  type AnalysisCallHeader,
  type AnalysisState,
  type CallAnalysis,
  type RedFlag,
  type Score,
  type Transcript,
} from './api'
import {
  BAND_LABEL,
  BAND_TONE,
  bandOf,
  blockLabel,
  failureHalfLabel,
  FAILURE_LABEL,
  outcomeLabel,
  QUALITY_LABEL,
  QUALITY_TONE,
  redFlagLabel,
  SENTIMENT_LABEL,
  SENTIMENT_TONE,
  STAGE_LABEL,
  STAGE_TONE,
} from './labels'
import {
  analysisView,
  blockRows,
  reviewReasonText,
  scoreTotals,
  speakerLane,
  speakerOrder,
  TRANSCRIPT_PREVIEW_LINES,
  transcriptLines,
} from './state'

// ───────────────────────────────────────────────────────────────────────────
//  The call this is about
// ───────────────────────────────────────────────────────────────────────────

/**
 * Which conversation, in one card.
 *
 * The same left-to-right reading as the call card in `modules/calls`: the
 * employee, an arrow for the direction, the client. It is rebuilt here rather
 * than imported because §7 forbids touching `CallDetailPage.tsx`, and the two
 * cards carry different fields — this one has no audio, no note and no
 * reconciliation, because the analysis response does not send them.
 */
function CallHeaderCard({ call }: { call: AnalysisCallHeader }) {
  const outgoing = call.direction === 'outgoing'
  const Arrow = outgoing ? ArrowRight : ArrowLeft
  const phone = formatPhone(call.remote_number)

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-2xs font-medium uppercase tracking-wide text-muted">
            {t('analysis.employeeSide')}
          </span>
          <span className="truncate text-lg font-semibold text-text">{call.agent_name}</span>
        </div>

        <div className="flex shrink-0 flex-col items-center gap-1 px-2">
          <Arrow className={cn('size-6', outgoing ? 'text-accent' : 'text-good')} aria-hidden />
          <span className="font-mono text-base tabular-nums text-text">
            {formatDuration(call.duration_sec)}
          </span>
        </div>

        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-2xs font-medium uppercase tracking-wide text-muted">
            {t('analysis.clientSide')}
          </span>
          <span className="truncate font-mono text-lg font-semibold text-text">
            {phone ?? t('analysis.numberWithheld')}
          </span>
        </div>

        <div
          className="ms-auto text-end text-xs text-muted"
          title={formatInstantTitle(call.started_at)}
        >
          {formatDateTime(call.started_at)}
        </div>
      </div>
    </Card>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The button — rendered only where the server would accept it
// ───────────────────────────────────────────────────────────────────────────

/**
 * `analysis:run` only. A `manager` reads scores and never sees this control,
 * which is the line the registry already draws at `settings:write`: pressing it
 * sends a customer recording to a vendor and spends money (§6.1).
 *
 * Hiding it is not access control — the server refuses the POST regardless —
 * but showing somebody a button that answers 403 is its own kind of wrong.
 */
function RunButton({ callId, retry }: { callId: string; retry: boolean }) {
  const can = useAuth((state) => state.can)
  const mutation = useQueueAnalysis()
  const busy = mutation.status === 'pending'

  if (!can(Perm.ANALYSIS_RUN)) return null

  return (
    <div className="flex flex-col items-start gap-2">
      <Button size="sm" disabled={busy} onClick={() => mutation.mutate(callId)}>
        {retry ? (
          <RotateCcw className="size-3.5" aria-hidden />
        ) : (
          <Play className="size-3.5" aria-hidden />
        )}
        {busy
          ? t('analysis.runBusy')
          : retry
            ? t('analysis.retryButton')
            : t('analysis.runButton')}
      </Button>
      {/* The four 409s — the flag is off, the call is not analysable, the cap
          is reached, no provider is configured — already have Uzbek sentences
          in `errors.*`, so this renders the catalogue rather than a code. */}
      {mutation.error ? (
        <p className="text-xs text-bad">{messageForError(mutation.error)}</p>
      ) : null}
      {mutation.status === 'success' ? (
        <p className="text-xs text-good">{t('analysis.runQueued')}</p>
      ) : null}
    </div>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The score block
// ───────────────────────────────────────────────────────────────────────────

function BlockBars({ score }: { score: Score }) {
  const rows = blockRows(score)
  if (rows.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => {
        const label = blockLabel(row.key)
        return (
          <div key={row.key} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs text-text">{label}</span>
              <span className="font-mono text-xs tabular-nums text-muted">
                {row.max === null ? row.score : `${row.score} / ${row.max}`}
              </span>
            </div>
            {/* No bar without a denominator. A bar drawn against an invented
                maximum is how a 167 % bar once reached a manager — the reason
                `BLOCK_MAX` is derived from the rubric on the server and never
                typed a second time. */}
            {row.max !== null && row.max > 0 ? (
              <ProgressBar
                fraction={row.score / row.max}
                tone={BAND_TONE[bandOf(Math.round((100 * row.score) / row.max))]}
                label={t('analysis.blockBar', {
                  block: label,
                  score: row.score,
                  max: row.max,
                })}
              />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function RedFlagList({ flags }: { flags: readonly RedFlag[] }) {
  if (flags.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {flags.map((flag, index) => (
        <div
          key={`${flag.type}-${index}`}
          className="rounded-md border border-bad/30 bg-bad/5 p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="bad">{redFlagLabel(flag.type, flag.label)}</Badge>
            {/* `counted` marks the one that actually moved the score — the
                penalty is charged once per type, so a repeat is evidence and
                not a second deduction. Saying so stops a manager adding the
                numbers up and getting a different total. */}
            {flag.counted ? (
              <span className="font-mono text-2xs tabular-nums text-bad">
                {t('analysis.flagPenalty', { penalty: flag.penalty })}
              </span>
            ) : (
              <span className="text-2xs text-muted">{t('analysis.flagRepeat')}</span>
            )}
            {flag.timestamp ? (
              <span className="font-mono text-2xs text-muted">{flag.timestamp}</span>
            ) : null}
          </div>
          {flag.quote ? (
            <p className="mt-1 text-xs italic text-text">{flag.quote}</p>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function ScoreSection({ score }: { score: Score }) {
  const totals = scoreTotals(score)
  const band = bandOf(score.overall_score)

  return (
    <Section
      title={t('analysis.sectionScore')}
      description={t('analysis.scoredAt', { at: formatDateTime(score.scored_at) })}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-4xl font-semibold tabular-nums text-text">
              {score.overall_score}
            </span>
            <Badge tone={BAND_TONE[band]}>{t(BAND_LABEL[band])}</Badge>
          </div>

          {/* ═══════════════════════════════════════════════════════════════
              "68 / 75", not "68 / 100".

              `meta.applicable_max` is the sum of the maxima of the blocks that
              were ACTUALLY assessed. Most Bonvi customers are returning
              customers who do not need a needs analysis or a product pitch, so
              a quarter of the rubric routinely does not apply — and a header
              that assumes 100 would make an employee who did everything right
              look like they lost 25 points. Printed only when the document
              carries the number; never invented (§7.4).
              ═══════════════════════════════════════════════════════════════ */}
          {totals.max !== null ? (
            <div className="flex flex-col">
              <span className="font-mono text-sm tabular-nums text-muted">
                {t('analysis.pointsOf', { earned: totals.earned, max: totals.max })}
              </span>
              {totals.naCount > 0 ? (
                <span className="text-2xs text-muted">
                  {t('analysis.naNote', { count: totals.naCount })}
                </span>
              ) : null}
            </div>
          ) : null}

          {score.needs_review ? (
            <Badge tone="warn" className="ms-auto">
              {t('analysis.reviewBadge')}
            </Badge>
          ) : null}
        </div>

        {score.needs_review && score.review_reasons.length > 0 ? (
          <ul className="flex flex-col gap-1 rounded-md border border-warn/30 bg-warn/5 p-3">
            {score.review_reasons.map((reason, index) => (
              <li key={index} className="text-xs text-text">
                {reviewReasonText(reason)}
              </li>
            ))}
          </ul>
        ) : null}

        <BlockBars score={score} />

        <RedFlagList flags={score.red_flags} />

        {score.coaching_note ? (
          <div className="rounded-md border border-border bg-surface-2 p-3">
            <p className="text-2xs font-medium uppercase tracking-wide text-muted">
              {t('analysis.coaching')}
            </p>
            <p className="mt-1 whitespace-pre-wrap text-sm text-text">{score.coaching_note}</p>
          </div>
        ) : null}

        <FieldGrid className="border-t border-border pt-3">
          <Field label={t('analysis.sentimentLabel')}>
            {score.sentiment ? (
              <Badge tone={SENTIMENT_TONE[score.sentiment]}>
                {t(SENTIMENT_LABEL[score.sentiment])}
              </Badge>
            ) : (
              <span className="text-muted">{EM_DASH}</span>
            )}
          </Field>
          <Field label={t('analysis.qualityLabel')}>
            <Badge tone={QUALITY_TONE[score.transcript_quality]}>
              {t(QUALITY_LABEL[score.transcript_quality])}
            </Badge>
          </Field>
          <Field
            label={t('analysis.confidenceLabel')}
            value={t('analysis.percent', { value: score.confidence_pct })}
          />
          <Field
            label={t('analysis.outcomeLabel')}
            value={score.outcome_signal ? outcomeLabel(score.outcome_signal.type) : null}
          />
          <Field
            label={t('analysis.productsLabel')}
            value={
              score.outcome_signal && score.outcome_signal.products_mentioned.length > 0
                ? score.outcome_signal.products_mentioned.join(', ')
                : null
            }
          />
          <Field
            label={t('analysis.modelLabel')}
            value={`${score.provider} · ${score.model}`}
            title={t('analysis.rubricVersion', { version: score.rubric_version })}
          />
        </FieldGrid>
      </div>
    </Section>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The transcript block
// ───────────────────────────────────────────────────────────────────────────

/**
 * The raw text, speakers visually separated, collapsed past ~15 lines.
 *
 * **Click-to-seek is phase 2.** The timestamps are rendered because they are
 * stored for exactly that, but wiring them now would mean touching
 * `AudioPlayer.tsx`, which this phase does not do (§7.4).
 */
function TranscriptSection({ transcript }: { transcript: Transcript }) {
  const [expanded, setExpanded] = useState(false)
  const lines = transcriptLines(transcript.text)
  const order = speakerOrder(lines)
  const collapsible = lines.length > TRANSCRIPT_PREVIEW_LINES
  const shown = collapsible && !expanded ? lines.slice(0, TRANSCRIPT_PREVIEW_LINES) : lines

  return (
    <Section
      title={t('analysis.sectionTranscript')}
      description={t('analysis.transcriptMeta', {
        words: formatCount(transcript.word_count),
        provider: transcript.provider,
        model: transcript.model,
      })}
    >
      {lines.length === 0 ? (
        <p className="text-sm text-muted">{t('analysis.transcriptEmpty')}</p>
      ) : (
        <>
          <div className="flex max-h-[32rem] flex-col gap-2 overflow-y-auto pe-1">
            {shown.map((line, index) => {
              const lane = speakerLane(line.speaker, order)
              return (
                <div
                  key={index}
                  className={cn(
                    'border-s-2 ps-3',
                    lane === 0 ? 'border-accent' : 'border-good',
                  )}
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    {line.speaker ? (
                      <span
                        className={cn(
                          'text-2xs font-medium uppercase tracking-wide',
                          lane === 0 ? 'text-accent' : 'text-good',
                        )}
                      >
                        {line.speaker}
                      </span>
                    ) : null}
                    {/* Read, not pressed: seek is phase 2. */}
                    {line.timestamp ? (
                      <span className="font-mono text-2xs text-muted">{line.timestamp}</span>
                    ) : null}
                  </div>
                  <p className="text-sm leading-snug text-text">{line.text}</p>
                </div>
              )
            })}
          </div>

          {collapsible ? (
            <Button
              variant="ghost"
              size="sm"
              className="mt-3"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? (
                <ChevronUp className="size-4" aria-hidden />
              ) : (
                <ChevronDown className="size-4" aria-hidden />
              )}
              {expanded
                ? t('analysis.transcriptCollapse')
                : t('analysis.transcriptExpand', {
                    count: formatCount(lines.length - TRANSCRIPT_PREVIEW_LINES),
                  })}
            </Button>
          ) : null}
        </>
      )}
    </Section>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The pipeline's own bookkeeping, for the states that need it
// ───────────────────────────────────────────────────────────────────────────

function StateFacts({ state }: { state: AnalysisState }) {
  return (
    <FieldGrid className="mt-3 border-t border-border pt-3">
      <Field label={t('analysis.attemptsLabel')} value={String(state.attempts)} />
      <Field
        label={t('analysis.queuedAt')}
        value={formatDateTimeOrDash(state.queued_at)}
        title={formatInstantTitle(state.queued_at)}
      />
      <Field label={t('analysis.lastRunAt')} value={formatDateTimeOrDash(state.last_run_at)} />
    </FieldGrid>
  )
}

// ───────────────────────────────────────────────────────────────────────────
//  The seven states of §7.4
// ───────────────────────────────────────────────────────────────────────────

function AnalysisCard({ data }: { data: CallAnalysis }) {
  const view = analysisView(data)

  // Row 1: the flag is off and nothing was ever analysed. "Tahlil o'chirilgan"
  // and nothing else — a disabled feature does not advertise itself, so there
  // is no call card, no button and no hint about what it would do.
  if (view.kind === 'disabled') {
    return (
      <Card className="flex flex-col items-center gap-2 p-10 text-center">
        <p className="text-sm font-medium text-text">{t('analysis.disabledTitle')}</p>
      </Card>
    )
  }

  const state = data.state

  return (
    <div className="flex flex-col gap-4">
      <CallHeaderCard call={data.call} />

      {/* Row 2: the rows exist but the flag is off. They are shown, read-only,
          and the note says why no button is offered — pressing one would
          answer 409 `analysis_disabled`. */}
      {view.readOnly ? (
        <Card className="flex items-center gap-3 border-warn/40 bg-warn/5 p-3">
          <AlertTriangle className="size-4 shrink-0 text-warn" aria-hidden />
          <p className="text-sm text-text">{t('analysis.readOnlyNote')}</p>
        </Card>
      ) : null}

      {view.kind === 'not_analysed' ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <p className="text-sm font-medium text-text">{t('analysis.notAnalysedTitle')}</p>
          <p className="max-w-md text-xs text-muted">{t('analysis.notAnalysedHint')}</p>
          {view.offersRun ? <RunButton callId={data.call_id} retry={false} /> : null}
        </Card>
      ) : null}

      {view.kind === 'running' && state ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <Loader2 className="size-6 animate-spin text-accent" aria-hidden />
          <p className="text-sm font-medium text-text">{t(STAGE_LABEL[state.stage])}</p>
          <p className="max-w-md text-xs text-muted">{t('analysis.runningHint')}</p>
        </Card>
      ) : null}

      {/* Row 5: NOT a failure and not painted as one. A call with no recording,
          or an internal call, was never a candidate — and the button is absent
          because the §2.6 gate would answer 409 `call_not_analysable` on every
          press. This is the row the precedence list exists to protect. */}
      {view.kind === 'skipped' && state ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STAGE_TONE[state.stage]}>{t(STAGE_LABEL[state.stage])}</Badge>
            <p className="text-sm text-text">
              {state.failure_code ? t(FAILURE_LABEL[state.failure_code]) : EM_DASH}
            </p>
          </div>
          <p className="mt-1 text-xs text-muted">{t('analysis.skippedHint')}</p>
        </Card>
      ) : null}

      {view.kind === 'failed' && state ? (
        <Card className="border-bad/40 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <AlertTriangle className="size-4 shrink-0 text-bad" aria-hidden />
                <p className="text-sm font-medium text-text">
                  {state.failure_code
                    ? t(FAILURE_LABEL[state.failure_code])
                    : t('analysis.failedTitle')}
                </p>
              </div>
              {failureHalfLabel(state.failure_stage) ? (
                <p className="mt-1 text-xs text-muted">
                  {t('analysis.failedHalf', {
                    half: failureHalfLabel(state.failure_stage) ?? '',
                  })}
                </p>
              ) : null}
            </div>
            {view.offersRun ? <RunButton callId={data.call_id} retry /> : null}
          </div>

          {/* The provider's own message, redacted server-side. Technical
              English beside the Uzbek headline, never instead of it — and in a
              muted monospace line so it reads as a diagnostic rather than as
              the sentence a user is meant to act on. */}
          {state.failure_detail ? (
            <p className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-surface-2 p-2 font-mono text-2xs text-muted">
              {state.failure_detail}
            </p>
          ) : null}

          <StateFacts state={state} />
        </Card>
      ) : null}

      {/* Row 7. Each block is rendered only if the server sent it: a state row
          that says `completed` with no score is not a shape this pipeline
          produces, and an empty section is a better answer than a crash. */}
      {view.kind === 'completed' ? (
        <>
          {data.score ? <ScoreSection score={data.score} /> : null}
          {data.transcript ? <TranscriptSection transcript={data.transcript} /> : null}
          {!data.score && !data.transcript ? (
            <Card className="p-10 text-center">
              <p className="text-sm text-muted">{t('analysis.completedEmpty')}</p>
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

export function AnalysisDetailPage() {
  const { callId } = useParams<{ callId: string }>()
  const analysisQuery = useCallAnalysis(callId)

  return (
    <Page>
      <PageHeader
        title={t('page.analysisDetail')}
        actions={
          <Link
            to="/analysis"
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t('analysis.back')}
          </Link>
        }
      />
      {/* A call belonging to another agent answers 404, so this page's error
          state is also its "not yours" state — and it says the same thing for
          both, which is the point of the server's choice. */}
      <QueryBoundary query={analysisQuery}>{(data) => <AnalysisCard data={data} />}</QueryBoundary>
    </Page>
  )
}
