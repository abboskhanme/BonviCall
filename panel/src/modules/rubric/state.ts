/**
 * The rubric editor's decisions, as pure functions with their own tests.
 *
 * Four of them are the kind that go wrong silently inside a component, which is
 * why none is written inline:
 *
 *  1. `rubricTotal()` / `blockTotal()` — **the save button is disabled until the
 *     blocks total exactly 100.** The server refuses anything else (422), so
 *     without this the admin fills the whole form, presses save and is told no.
 *     The arithmetic is here and tested, not counted by eye in JSX.
 *
 *  2. `slugify()` — the red-flag key is derived from the label, because the key
 *     is a technical string the model must echo back verbatim and the admin
 *     thinks in sentences. A key with a space or a capital makes EVERY answer
 *     fail validation, i.e. one careless save stops all scoring.
 *
 *  3. `isDirty()` — comparing the draft with what the server sent. Without it
 *     the button offers to publish a version identical to the live one, and the
 *     history fills with versions nobody changed.
 *
 *  4. `messageOfInvalid()` — the server refuses with a machine `reason` and the
 *     numbers; the sentence lives in `uz.json` (CONVENTIONS.md §14). A payload
 *     never carries display copy, which is the rule `review_reasons` already
 *     follows.
 *
 * The edit operations return NEW arrays. React state is replaced, never mutated
 * in place — a criterion edited in place does not re-render the block it is in.
 */
import { t, type MessageKey, type MessageVars } from '@/shared/i18n'
import { ApiError } from '@/shared/api/errors'

import type { Rubric, RubricBlock, RubricCriterion, RubricRedFlag } from './api'

/** What the page holds while it is being edited, before anything is published. */
export interface RubricDraft {
  blocks: RubricBlock[]
  redFlags: RubricRedFlag[]
  extraRules: string
}

/** The draft a freshly loaded rubric starts as. */
export function draftOf(rubric: Rubric): RubricDraft {
  return {
    blocks: rubric.blocks.map((block) => ({
      ...block,
      criteria: block.criteria.map((criterion) => ({ ...criterion })),
    })),
    redFlags: rubric.red_flags.map((flag) => ({ ...flag })),
    // `null` and `''` are one thing on the wire — "no instructions" — and the
    // textarea needs a string.
    extraRules: rubric.extra_rules ?? '',
  }
}

// ───────────────────────────────────────────────────────────────────────────
//  1. The arithmetic the server will check anyway
// ───────────────────────────────────────────────────────────────────────────

/** What a block's criteria actually add up to. */
export function blockTotal(block: RubricBlock): number {
  return block.criteria.reduce((sum, criterion) => sum + criterion.points, 0)
}

/** What the whole rubric adds up to. Must be exactly 100 to be publishable. */
export function rubricTotal(blocks: readonly RubricBlock[]): number {
  return blocks.reduce((sum, block) => sum + block.max, 0)
}

/** The points a score is out of. Duplicated from the server deliberately —
 *  disabling the button needs it before any request is made — and the server
 *  remains the only thing that decides (`rubric_service.TOTAL_POINTS`). */
export const TOTAL_POINTS = 100

/** Whether every block reaches its own maximum and the blocks reach 100. */
export function isPublishable(draft: RubricDraft): boolean {
  return (
    draft.blocks.length > 0 &&
    rubricTotal(draft.blocks) === TOTAL_POINTS &&
    draft.blocks.every(
      (block) => block.criteria.length > 0 && blockTotal(block) === block.max,
    )
  )
}

/** Whether anything at all has been changed since the server's answer. */
export function isDirty(draft: RubricDraft, rubric: Rubric): boolean {
  return JSON.stringify(draft) !== JSON.stringify(draftOf(rubric))
}

// ───────────────────────────────────────────────────────────────────────────
//  2. The red-flag key
// ───────────────────────────────────────────────────────────────────────────

/** The server's `RED_FLAG_KEY`, character for character. Checked here as well
 *  so a bad key is caught before a round trip loses the form's contents. */
export const FLAG_KEY = /^[a-z][a-z0-9_]{1,31}$/

/**
 * A label turned into a key the model can echo back.
 *
 * The admin writes "Mijozni shaxsiy raqamga o'g'dirish"; the prompt, the
 * validator and the stored score all need `mijozni_shaxsiy_raqamga_ogdirish`.
 * Making them type that themselves is a source of errors with no upside.
 */
export function slugify(label: string): string {
  const FOLD: Record<string, string> = {
    'ʻ': '', 'ʼ': '', "'": '', '‘': '', '’': '', '`': '',
    'ў': 'o', 'қ': 'q', 'ғ': 'g', 'ҳ': 'h',
  }
  return label
    .toLowerCase()
    .split('')
    .map((character) => FOLD[character] ?? character)
    .join('')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 32)
}

export type FlagKeyState = 'ok' | 'invalid' | 'duplicate'

/** Whether a derived key may be added to `flags`. */
export function flagKeyState(key: string, flags: readonly RubricRedFlag[]): FlagKeyState {
  if (!FLAG_KEY.test(key)) return 'invalid'
  return flags.some((flag) => flag.type === key) ? 'duplicate' : 'ok'
}

// ───────────────────────────────────────────────────────────────────────────
//  3. Editing, without mutating
// ───────────────────────────────────────────────────────────────────────────

export function replaceCriterion(
  blocks: readonly RubricBlock[],
  blockIndex: number,
  index: number,
  criterion: RubricCriterion,
): RubricBlock[] {
  return blocks.map((block, bi) =>
    bi !== blockIndex
      ? block
      : { ...block, criteria: block.criteria.map((old, ci) => (ci === index ? criterion : old)) },
  )
}

export function addCriterion(
  blocks: readonly RubricBlock[],
  blockIndex: number,
  criterion: RubricCriterion,
): RubricBlock[] {
  return blocks.map((block, bi) =>
    bi !== blockIndex ? block : { ...block, criteria: [...block.criteria, criterion] },
  )
}

export function removeCriterion(
  blocks: readonly RubricBlock[],
  blockIndex: number,
  index: number,
): RubricBlock[] {
  return blocks.map((block, bi) =>
    bi !== blockIndex
      ? block
      : { ...block, criteria: block.criteria.filter((_, ci) => ci !== index) },
  )
}

export function replaceBlock(
  blocks: readonly RubricBlock[],
  index: number,
  changes: { label: string; max: number },
): RubricBlock[] {
  return blocks.map((block, bi) => (bi === index ? { ...block, ...changes } : block))
}

export function replaceFlag(
  flags: readonly RubricRedFlag[],
  index: number,
  flag: RubricRedFlag,
): RubricRedFlag[] {
  return flags.map((old, fi) => (fi === index ? flag : old))
}

/** The id a new criterion is proposed under: `A1`, `A2`, … within its block. */
export function nextCriterionId(block: RubricBlock): string {
  const prefix = (block.key[0] ?? 'x').toUpperCase()
  return `${prefix}${block.criteria.length + 1}`
}

// ───────────────────────────────────────────────────────────────────────────
//  4. The server's refusal, as a sentence
// ───────────────────────────────────────────────────────────────────────────

/** The reasons `rubric_service.validate_rubric` can refuse with. */
const INVALID_REASON: Record<string, MessageKey> = {
  rubric_no_blocks: 'rubric.invalid.rubric_no_blocks',
  rubric_block_empty: 'rubric.invalid.rubric_block_empty',
  rubric_block_mismatch: 'rubric.invalid.rubric_block_mismatch',
  rubric_total_not_100: 'rubric.invalid.rubric_total_not_100',
  rubric_flag_penalty_positive: 'rubric.invalid.rubric_flag_penalty_positive',
  rubric_flag_key_invalid: 'rubric.invalid.rubric_flag_key_invalid',
  rubric_flag_key_duplicate: 'rubric.invalid.rubric_flag_key_duplicate',
  rubric_extra_rules_too_long: 'rubric.invalid.rubric_extra_rules_too_long',
  rubric_version_taken: 'rubric.invalid.rubric_version_taken',
}

/**
 * The Uzbek sentence for a refusal, or `null` when this is not one of ours.
 *
 * The caller falls back to `messageForError`, which renders the envelope's code
 * — so an error nobody anticipated still reads as a sentence rather than as a
 * blank space.
 */
export function messageOfInvalid(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  const detail = error.detail
  if (detail === null || typeof detail !== 'object' || Array.isArray(detail)) return null
  const reason = (detail as Record<string, unknown>).reason
  if (typeof reason !== 'string') return null
  const key = INVALID_REASON[reason]
  if (!key) return null
  const vars: MessageVars = {}
  for (const [name, value] of Object.entries(detail as Record<string, unknown>)) {
    if (typeof value === 'string' || typeof value === 'number') vars[name] = value
  }
  return t(key, vars)
}
