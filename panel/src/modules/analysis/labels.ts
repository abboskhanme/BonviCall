/**
 * The closed server enums, rendered in Uzbek (SPEC-ANALYTICS §7.6).
 *
 * The maps over a CLOSED enum are `Record<<enum>, MessageKey>` over a type from
 * `types.gen.ts`, the same shape `modules/calls/labels.ts` uses and for the same
 * reason: the day the server adds a nineteenth-and-a-half `AnalysisFailure`,
 * `make types` widens the union and this file stops compiling, so a new reason
 * cannot reach the screen as a raw snake_case identifier. A `Partial<>` or a
 * `??` fallback on those maps would turn the compile error back into a silent
 * gap.
 *
 * Three vocabularies here are **deliberately open**, and each says so at its
 * declaration: the rubric's block keys, its red-flag keys and its outcome
 * vocabulary. They live inside JSONB documents written under a pinned
 * `rubric_version` (`RedFlagOut.type`: "the panel renders an unknown key as the
 * key"), so a score written under v1 must stay readable after v2 adds a flag.
 * Those three are looked up through a function that falls back to the key
 * rather than through a total `Record`.
 *
 * The Uzbek text itself lives in `shared/i18n/uz.json`; only keys appear here
 * (CONVENTIONS.md §14).
 */
import { t, type MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

import type { AnalysisFailure, AnalysisStage, ScoreBand } from './api'

export type CallSentiment = components['schemas']['CallSentiment']
export type TranscriptQuality = components['schemas']['TranscriptQuality']

export type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'accent'

// --- Where a call stands (§2.4) ---------------------------------------------

export const STAGE_LABEL: Record<AnalysisStage, MessageKey> = {
  queued: 'analysis.stage.queued',
  transcribing: 'analysis.stage.transcribing',
  scoring: 'analysis.stage.scoring',
  completed: 'analysis.stage.completed',
  skipped: 'analysis.stage.skipped',
  failed: 'analysis.stage.failed',
}

/**
 * `skipped` is **neutral, never red** (§2.4, §7.4: "No error styling — this is
 * not a failure").
 *
 * A call with no recording, or an internal call, was never a candidate for
 * analysis. Painting it as a fault is the same mistake `modules/calls/labels.ts`
 * documents for retention-expired audio: it trains people to ignore the colour
 * that means an actual failure.
 */
export const STAGE_TONE: Record<AnalysisStage, BadgeTone> = {
  queued: 'neutral',
  transcribing: 'accent',
  scoring: 'accent',
  completed: 'good',
  skipped: 'neutral',
  failed: 'bad',
}

// --- Why a call stopped (§2.4) -----------------------------------------------

/**
 * All nineteen `AnalysisFailure` values, each an Uzbek headline.
 *
 * These are **not** `ErrorCode`s and never travel as an HTTP status (§6.3):
 * they are written to `call_analysis_state.failure_code` and read back here.
 * Mixing the two vocabularies would put nineteen codes into the wire contract
 * to describe things no request ever caused.
 */
export const FAILURE_LABEL: Record<AnalysisFailure, MessageKey> = {
  no_audio: 'analysis.failure.no_audio',
  audio_expired: 'analysis.failure.audio_expired',
  call_too_short: 'analysis.failure.call_too_short',
  call_type_unknown: 'analysis.failure.call_type_unknown',
  call_type_internal: 'analysis.failure.call_type_internal',
  provider_rate_limit: 'analysis.failure.provider_rate_limit',
  provider_cooldown: 'analysis.failure.provider_cooldown',
  provider_unavailable: 'analysis.failure.provider_unavailable',
  provider_network: 'analysis.failure.provider_network',
  interrupted: 'analysis.failure.interrupted',
  timeout: 'analysis.failure.timeout',
  transcript_empty: 'analysis.failure.transcript_empty',
  score_invalid: 'analysis.failure.score_invalid',
  ai_not_configured: 'analysis.failure.ai_not_configured',
  provider_auth: 'analysis.failure.provider_auth',
  provider_model: 'analysis.failure.provider_model',
  sdk_missing: 'analysis.failure.sdk_missing',
  audio_too_large: 'analysis.failure.audio_too_large',
  internal: 'analysis.failure.internal',
}

/** `failure_stage` — which half spent money before stopping. A plain string on
 *  the wire, admitted by a CHECK constraint to exactly these two. */
export const FAILURE_HALF_LABEL: Record<string, MessageKey> = {
  transcribe: 'analysis.half.transcribe',
  score: 'analysis.half.score',
}

export function failureHalfLabel(half: string | null): string | null {
  if (!half) return null
  const key = FAILURE_HALF_LABEL[half]
  return key ? t(key) : half
}

// --- The score band (§7.3) ---------------------------------------------------

export const BAND_LABEL: Record<ScoreBand, MessageKey> = {
  excellent: 'analysis.band.excellent',
  good: 'analysis.band.good',
  average: 'analysis.band.average',
  poor: 'analysis.band.poor',
}

/**
 * Narrower than `BadgeTone` on purpose: a band's tone has to satisfy both
 * `Badge` (which also knows `neutral`) and `ProgressBar` (which also knows
 * `accent`), and the intersection of the two is these three. Typing it as the
 * wider set puts a cast at every bar, which is a cast that would one day be
 * wrong.
 */
export type BandTone = Extract<BadgeTone, 'good' | 'warn' | 'bad'>

export const BAND_TONE: Record<ScoreBand, BandTone> = {
  excellent: 'good',
  good: 'good',
  average: 'warn',
  poor: 'bad',
}

/**
 * The thresholds, mirrored from `analysis/entities.py::ScoreSummary.grade`.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * A second copy of three numbers, and it is written down here on purpose
 * rather than pretended away. The server owns the definition — the list's
 * `score_band` filter is translated by `SCORE_BAND_RANGE`, which is *derived*
 * from this same property at import — but a row already on screen carries only
 * `overall_score`, and colouring it needs the boundaries. Asking the server per
 * row is fifty requests; adding a `band` field to `AnalysisListItem` is a
 * server change this task does not own.
 *
 * So the numbers are here, named, with a test that pins all four boundaries. If
 * the server moves a threshold, that test is what fails.
 * ═══════════════════════════════════════════════════════════════════════════
 */
const BAND_FLOOR: readonly (readonly [number, ScoreBand])[] = [
  [85, 'excellent'],
  [70, 'good'],
  [55, 'average'],
]

export function bandOf(score: number): ScoreBand {
  for (const [floor, band] of BAND_FLOOR) {
    if (score >= floor) return band
  }
  return 'poor'
}

// --- The rubric's own vocabularies, open by design ---------------------------

/**
 * The four blocks of rubric v1. An OPEN map: `ScoreResponse.blocks` is
 * `{[block_key]: points}` keyed by the rubric's own keys precisely so "a rubric
 * change must not need a server release to render", and a block v2 introduces
 * must appear as its key rather than as a blank bar.
 */
export const BLOCK_LABEL: Record<string, MessageKey> = {
  script: 'analysis.block.script',
  communication: 'analysis.block.communication',
  resolution: 'analysis.block.resolution',
  sales_skill: 'analysis.block.sales_skill',
}

/** The order the blocks are read in — the rubric's own order, A to D. A key
 *  outside this list still renders, after these, in the order the server sent. */
export const BLOCK_ORDER: readonly string[] = [
  'script',
  'communication',
  'resolution',
  'sales_skill',
]

export function blockLabel(key: string): string {
  const messageKey = BLOCK_LABEL[key]
  return messageKey ? t(messageKey) : key
}

/** The six red flags of rubric v1. Open, for the same reason as the blocks. */
export const RED_FLAG_LABEL: Record<string, MessageKey> = {
  profanity: 'analysis.redFlag.profanity',
  shouting: 'analysis.redFlag.shouting',
  unrealistic_promise: 'analysis.redFlag.unrealistic_promise',
  badmouthing: 'analysis.redFlag.badmouthing',
  off_policy_deal: 'analysis.redFlag.off_policy_deal',
  ignored_complaint: 'analysis.redFlag.ignored_complaint',
}

/**
 * A red flag's name.
 *
 * `fallback` is `RedFlagOut.label`, which the rubric carries in Uzbek already
 * (`rubric_default.py` is the one file allow-listed for Uzbek, §1.6). The list
 * endpoint sends only `red_flag_types` and has no label to offer, which is why
 * the catalogue is consulted first: one wording for the chip on the list and
 * the chip on the card.
 */
export function redFlagLabel(type: string, fallback?: string | null): string {
  const messageKey = RED_FLAG_LABEL[type]
  if (messageKey) return t(messageKey)
  return fallback && fallback.trim() !== '' ? fallback : type
}

/** How the conversation ended, when it said so (`validator.VALID_OUTCOMES`). */
export const OUTCOME_LABEL: Record<string, MessageKey> = {
  order_agreed: 'analysis.outcome.order_agreed',
  follow_up: 'analysis.outcome.follow_up',
  rejected: 'analysis.outcome.rejected',
  info_only: 'analysis.outcome.info_only',
  unclear: 'analysis.outcome.unclear',
}

export function outcomeLabel(type: string): string {
  const messageKey = OUTCOME_LABEL[type]
  return messageKey ? t(messageKey) : type
}

/**
 * Why a score is in the review queue (`analysis/rules.py::ReviewReason`).
 *
 * Six codes, not the four §7.6 estimated: `low_transcript_quality` and
 * `na_over_budget` were added when the rules were ported. The column holds
 * `[{code, params}]` and never display copy (§1.6), so every sentence — and
 * every `{placeholder}` in it — lives in `uz.json`.
 */
export const REVIEW_REASON_LABEL: Record<string, MessageKey> = {
  low_confidence: 'analysis.review.low_confidence',
  low_transcript_quality: 'analysis.review.low_transcript_quality',
  short_transcript: 'analysis.review.short_transcript',
  sparse_transcript: 'analysis.review.sparse_transcript',
  red_flag: 'analysis.review.red_flag',
  na_over_budget: 'analysis.review.na_over_budget',
}

// --- What the model heard ----------------------------------------------------

export const SENTIMENT_LABEL: Record<CallSentiment, MessageKey> = {
  positive: 'analysis.sentiment.positive',
  neutral: 'analysis.sentiment.neutral',
  negative: 'analysis.sentiment.negative',
}

export const SENTIMENT_TONE: Record<CallSentiment, BadgeTone> = {
  positive: 'good',
  neutral: 'neutral',
  negative: 'bad',
}

export const QUALITY_LABEL: Record<TranscriptQuality, MessageKey> = {
  high: 'analysis.quality.high',
  medium: 'analysis.quality.medium',
  low: 'analysis.quality.low',
}

export const QUALITY_TONE: Record<TranscriptQuality, BadgeTone> = {
  high: 'good',
  medium: 'warn',
  low: 'bad',
}

/** `ProviderCooldownResponse.role` — one cooldown per role, and the two names
 *  a person reads are not "asr" and "llm". */
export const COOLDOWN_ROLE_LABEL: Record<string, MessageKey> = {
  asr: 'analysis.role.asr',
  llm: 'analysis.role.llm',
}

export function cooldownRoleLabel(role: string): string {
  const messageKey = COOLDOWN_ROLE_LABEL[role]
  return messageKey ? t(messageKey) : role
}
