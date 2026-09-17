/**
 * The decisions §7.4 makes, as pure functions with their own tests.
 *
 * Three of them are the kind that go wrong silently on a page, which is why
 * none of them is written inline in a component:
 *
 *  1. `analysisView()` — **an ordered precedence list, not a set of cases.**
 *     The first two rows overlap with the rest, and a reader who takes them as
 *     an unordered set renders a "Tahlil qilish" button on a call whose feature
 *     flag is off, which answers 409 `analysis_disabled`.
 *
 *  2. `blockRows()` / `scoreTotals()` — a block whose criteria were ALL marked
 *     "does not apply" is absent from `blocks` while sitting in
 *     `block_details.blocks` with `score: 0`. Reading the wrong one of those two
 *     draws a 0 bar for work nobody was assessed on, in front of a manager.
 *     And the header reads "68 / 75" from `meta.applicable_max` rather than
 *     assuming a denominator of 100.
 *
 *  3. `monthCost()` — `priced: false` is what stops the panel rendering $0.00
 *     and implying the feature is free (§11.1). A cost of zero because nobody
 *     typed a price is not a free feature.
 */
import { redFlagLabel, REVIEW_REASON_LABEL } from './labels'
import type { AnalysisMonth, AnalysisStage, CallAnalysis, Score } from './api'
import { isRunningStage } from './api'
import { t, type MessageKey, type MessageVars } from '@/shared/i18n'

// ───────────────────────────────────────────────────────────────────────────
//  1. The §7.4 precedence list
// ───────────────────────────────────────────────────────────────────────────

export type AnalysisViewKind =
  | 'disabled'
  | 'not_analysed'
  | 'running'
  | 'skipped'
  | 'failed'
  | 'completed'

export interface AnalysisView {
  kind: AnalysisViewKind
  /**
   * Whether this state has anything for the button to do. **Still ANDed with
   * `analysis:run` at the call site** — this answers "would the server accept
   * it", not "may this person ask".
   */
  offersRun: boolean
  /** The flag is off but rows exist: show them, offer nothing (§7.4 row 3). */
  readOnly: boolean
}

function kindOfStage(stage: AnalysisStage): AnalysisViewKind {
  if (isRunningStage(stage)) return 'running'
  if (stage === 'skipped') return 'skipped'
  if (stage === 'failed') return 'failed'
  return 'completed'
}

/**
 * Which of §7.4's rows this response is. **Evaluated in order; first match
 * wins.**
 *
 * | # | Server state | What the page shows |
 * |---|---|---|
 * | 1 | `enabled` false AND `state` null | "Tahlil o'chirilgan" and nothing else |
 * | 2 | `enabled` false AND rows exist | the rows, read-only, no button |
 * | 3 | no state row | "Tahlil qilinmagan" + the button |
 * | 4 | queued / transcribing / scoring | the stage, with a spinner; polls |
 * | 5 | `skipped` | one sentence from `failure_code`; NOT an error |
 * | 6 | `failed` | the headline, the retry button, `failure_detail` |
 * | 7 | `completed` | the score block and the transcript block |
 *
 * Row 5 is the one that costs money to get wrong the other way: `skipped`
 * means the call failed the §2.6 gate — no audio, too short, not an external
 * answered call — so a retry button there answers 409 `call_not_analysable`
 * every single time. `completed` offers no button either: re-scoring needs
 * `force: true`, which is the only way to spend twice on one call, and §7.4
 * does not put that control on this page.
 */
export function analysisView(data: CallAnalysis): AnalysisView {
  const state = data.state

  // Row 1. A disabled feature does not advertise itself.
  if (!data.enabled && state === null) {
    return { kind: 'disabled', offersRun: false, readOnly: false }
  }

  // Row 2. Rows exist, the flag is off: everything below renders, read-only.
  const readOnly = !data.enabled

  // Row 3. Reached only with the flag ON, because row 1 already took the
  // flag-off half of this condition.
  if (state === null) {
    return { kind: 'not_analysed', offersRun: true, readOnly: false }
  }

  // Rows 4-7.
  const kind = kindOfStage(state.stage)
  return { kind, offersRun: !readOnly && kind === 'failed', readOnly }
}

// ───────────────────────────────────────────────────────────────────────────
//  2. The score block
// ───────────────────────────────────────────────────────────────────────────

/** `block_details` is a JSONB document (`{[key: string]: unknown}` on the wire,
 *  because a read endpoint that validated yesterday's document against today's
 *  enum would answer 500 for a row nobody can repair). These two readers are
 *  what let it be read without `any` and without trusting its shape. */
function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function numberAt(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function metaOf(score: Score): Record<string, unknown> | null {
  return asRecord(asRecord(score.block_details)?.['meta'])
}

function detailBlocksOf(score: Score): Record<string, unknown> | null {
  return asRecord(asRecord(score.block_details)?.['blocks'])
}

export interface BlockRow {
  key: string
  /** The block figure, already normalised to the criteria that applied.
   *  **Never recomputed here** — §7.4 is explicit about that. */
  score: number
  /** The block's own maximum, from `block_details.blocks[key].max`. Null when
   *  the document does not carry one, and then no bar is drawn: a bar with an
   *  invented denominator is how a 167 % bar once reached a manager. */
  max: number | null
}

/**
 * The bars to draw, in the rubric's own order.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **The rows come from `score.blocks` and from nowhere else.** A block whose
 * criteria were all "does not apply" is absent from that map by construction
 * (`validator.py`: "A block that applies not at all is not shown. Writing 0
 * would make the employee look at fault") — while `block_details.blocks` still
 * carries it with `score: 0`, `applicable_max: 0`, for the evidence trail.
 *
 * Iterating the wrong one of those two draws a zero bar for a block nobody was
 * assessed on. A row whose `applicable_max` is explicitly 0 is dropped as well,
 * so a hand-edited document cannot reintroduce the bar either.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function blockRows(score: Score): BlockRow[] {
  const details = detailBlocksOf(score)
  const keys = Object.keys(score.blocks)
  const ordered = [
    ...BLOCK_SORT.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !BLOCK_SORT.includes(key)),
  ]

  const rows: BlockRow[] = []
  for (const key of ordered) {
    const value = score.blocks[key]
    if (typeof value !== 'number' || !Number.isFinite(value)) continue
    const detail = asRecord(details?.[key])
    // Belt and braces: `blocks` already omits an unassessed block, and this
    // drops one that somehow survived into it.
    if (numberAt(detail, 'applicable_max') === 0) continue
    rows.push({ key, score: value, max: numberAt(detail, 'max') })
  }
  return rows
}

/** The rubric's own order, A to D. Kept beside `blockRows` rather than imported
 *  from labels so the sort and the lookup cannot be re-ordered independently. */
const BLOCK_SORT: readonly string[] = ['script', 'communication', 'resolution', 'sales_skill']

export interface ScoreTotals {
  /** `meta.blocks_total` — the block figures added up. */
  earned: number
  /** `meta.applicable_max` — the maxima of the blocks that WERE assessed.
   *  Null when the document does not carry it, and then the page prints no
   *  fraction at all rather than assuming 100 (§7.4). */
  max: number | null
  /** How many criteria the model marked "does not apply to this conversation". */
  naCount: number
}

export function scoreTotals(score: Score): ScoreTotals {
  const meta = metaOf(score)
  const blocksTotal = numberAt(meta, 'blocks_total')
  const applicableMax = numberAt(meta, 'applicable_max')
  const na = meta?.['na_criteria']

  const earned =
    blocksTotal ??
    Object.values(score.blocks).reduce(
      (sum, value) => (typeof value === 'number' && Number.isFinite(value) ? sum + value : sum),
      0,
    )

  return {
    earned,
    max: applicableMax !== null && applicableMax > 0 ? applicableMax : null,
    naCount: Array.isArray(na) ? na.length : 0,
  }
}

// ───────────────────────────────────────────────────────────────────────────
//  Review reasons — a machine code plus params, never display copy (§1.6)
// ───────────────────────────────────────────────────────────────────────────

function toVars(code: string, params: Record<string, unknown> | null): MessageVars {
  const vars: MessageVars = {}
  for (const [key, value] of Object.entries(params ?? {})) {
    if (typeof value === 'number' || typeof value === 'string') {
      vars[key] = value
    } else if (Array.isArray(value)) {
      // `red_flag` carries `types`, the rubric's own keys. The sentence a
      // manager reads names the breaches, not their identifiers.
      vars[key] = value
        .filter((item): item is string => typeof item === 'string')
        .map((item) => (code === 'red_flag' ? redFlagLabel(item) : item))
        .join(', ')
    }
  }
  return vars
}

/**
 * One review reason as its Uzbek sentence.
 *
 * An unrecognised code renders as the code rather than disappearing: a call is
 * in the review queue for a reason, and a blank line is the one answer this
 * block may not give.
 */
export function reviewReasonText(reason: Record<string, unknown>): string {
  const code = typeof reason['code'] === 'string' ? reason['code'] : ''
  const messageKey: MessageKey | undefined = REVIEW_REASON_LABEL[code]
  if (!messageKey) return code
  return t(messageKey, toVars(code, asRecord(reason['params'])))
}

// ───────────────────────────────────────────────────────────────────────────
//  3. The month's spend — and why zero is not a number to print
// ───────────────────────────────────────────────────────────────────────────

const MICRO_PER_USD = 1_000_000

/** `12_340_000` → `$12.34`. The symbol stays Latin: it is read the same in
 *  Uzbek and translating a currency sign makes it harder, not easier. */
export function formatMicroUsd(micro: number): string {
  return `$${(micro / MICRO_PER_USD).toFixed(2)}`
}

export interface MonthCost {
  /** The figure, or null while no vendor price has been entered. */
  text: string | null
  cap: string | null
}

/**
 * What the month has cost — or nothing at all.
 *
 * `priced: false` means no admin has entered a vendor price yet, so
 * `cost_micro_usd` is 0 because nothing was multiplied, not because nothing was
 * spent. Printing "$0.00" there tells a reader the feature is free, which is
 * the one wrong answer this page can give (§11.1). The call cap is what
 * actually protects the account until then, and it is shown instead.
 */
export function monthCost(month: AnalysisMonth): MonthCost {
  if (!month.priced) return { text: null, cap: null }
  return {
    text: formatMicroUsd(month.cost_micro_usd),
    cap: formatMicroUsd(month.cap_micro_usd),
  }
}

// ───────────────────────────────────────────────────────────────────────────
//  The transcript
// ───────────────────────────────────────────────────────────────────────────

/** Beyond this many lines the transcript is collapsed (§7.4). */
export const TRANSCRIPT_PREVIEW_LINES = 15

export interface TranscriptLine {
  /** `[00:12]`, when the provider located the line. **Not a control** —
   *  click-to-seek is phase 2 and would mean touching `AudioPlayer.tsx`, which
   *  this phase does not do. */
  timestamp: string | null
  speaker: string | null
  text: string
}

/**
 * Mirrors `analysis/rules.py`'s two service-token patterns, in the same order
 * and with the same character class: a line reads `[00:02] SPEAKER_0: ...`, and
 * the timestamp is stripped first because the speaker is anchored behind it.
 *
 * The class is copied rather than loosened to "anything before a colon" on
 * purpose. `count_words` on the server decides what a speaker prefix is with
 * exactly these characters, and `word_count` is stored so "the review rule and
 * the panel agree on one number" — a panel that split lines differently would
 * be a second opinion about the same text.
 */
const LINE =
  /^\s*(?:(\[\d{1,2}:\d{2}(?::\d{2})?\])\s*)?(?:([A-Za-zА-Яа-яЎўҚқҒғҲҳ_0-9 .'-]{1,32}):\s*)?([\s\S]*)$/

export function transcriptLines(text: string): TranscriptLine[] {
  return text
    .split('\n')
    .map((line) => line.trimEnd())
    .filter((line) => line.trim() !== '')
    .map((line) => {
      const match = LINE.exec(line)
      if (!match) return { timestamp: null, speaker: null, text: line }
      return {
        timestamp: match[1] ?? null,
        speaker: match[2]?.trim() ?? null,
        text: (match[3] ?? '').trim(),
      }
    })
}

/**
 * Which visual lane a line belongs to.
 *
 * Two speakers is the normal case and the only one worth distinguishing: the
 * employee and the client. A third speaker shares the second lane rather than
 * inventing a colour, because the point is "these two are different people",
 * not a legend.
 */
export function speakerLane(speaker: string | null, order: readonly string[]): 0 | 1 {
  // Lane 0 belongs to whoever spoke first — the employee, on every call this
  // pipeline scores. A line with no speaker at all shares it rather than
  // inventing a third treatment for what is usually a continuation.
  if (speaker === null) return 0
  return speaker === order[0] ? 0 : 1
}

/** The distinct speakers, in the order they first spoke. */
export function speakerOrder(lines: readonly TranscriptLine[]): string[] {
  const seen: string[] = []
  for (const line of lines) {
    if (line.speaker !== null && !seen.includes(line.speaker)) seen.push(line.speaker)
  }
  return seen
}
