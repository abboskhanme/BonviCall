/**
 * Complete fixtures, so a field the server ADDS breaks this file rather than
 * being quietly absent from every test in the module.
 *
 * Each builder returns a whole generated type with no `Partial<>` escape on the
 * base object — the same shape `modules/calls/__tests__/CallsPage.test.tsx`
 * sets, and for the same reason: a fixture that drifts from the contract makes
 * every assertion built on it worthless.
 */
import type { components } from '@/shared/api/types.gen'

export type AnalysisCallHeader = components['schemas']['AnalysisCallHeader']
export type AnalysisListItem = components['schemas']['AnalysisListItem']
export type AnalysisPage = components['schemas']['AnalysisListResponse']
export type AnalysisState = components['schemas']['AnalysisStateResponse']
export type AnalysisStatus = components['schemas']['AnalysisStatusResponse']
export type CallAnalysis = components['schemas']['CallAnalysisResponse']
export type Score = components['schemas']['ScoreResponse']
export type Transcript = components['schemas']['TranscriptResponse']

export const CALL_ID = '22222222-2222-4222-8222-222222222222'
export const AGENT_ID = '11111111-1111-4111-8111-111111111111'

export function makeCallHeader(
  overrides: Partial<AnalysisCallHeader> = {},
): AnalysisCallHeader {
  return {
    call_id: CALL_ID,
    started_at: '2026-09-15T10:12:00+05:00',
    agent_id: AGENT_ID,
    agent_name: 'Aziz Karimov',
    remote_number: '+998901112233',
    duration_sec: 184,
    direction: 'outgoing',
    disposition: 'answered',
    call_type: 'external',
    ...overrides,
  }
}

export function makeState(overrides: Partial<AnalysisState> = {}): AnalysisState {
  return {
    stage: 'completed',
    attempts: 1,
    asr_calls: 1,
    llm_calls: 1,
    cost_micro_usd: 0,
    queued_at: '2026-09-15T10:20:00+05:00',
    last_run_at: '2026-09-15T10:21:00+05:00',
    transcribed_at: '2026-09-15T10:21:30+05:00',
    scored_at: '2026-09-15T10:22:00+05:00',
    failure_code: null,
    failure_stage: null,
    failure_detail: null,
    ...overrides,
  }
}

/** A score where all four blocks were assessed: 78 out of a full 100. */
export function makeScore(overrides: Partial<Score> = {}): Score {
  return {
    overall_score: 78,
    blocks: { script: 20, communication: 18, resolution: 22, sales_skill: 18 },
    block_details: {
      blocks: {
        script: { score: 20, max: 25, raw_score: 20, applicable_max: 25 },
        communication: { score: 18, max: 25, raw_score: 18, applicable_max: 25 },
        resolution: { score: 22, max: 25, raw_score: 22, applicable_max: 25 },
        sales_skill: { score: 18, max: 25, raw_score: 18, applicable_max: 25 },
      },
      meta: {
        blocks_total: 78,
        applicable_max: 100,
        applicable_points: 100,
        earned_points: 78,
        na_criteria: [],
        na_over_budget: false,
        warnings: [],
        scenario: 'new_client',
        penalty_total: 0,
        zeroed_by_red_flag: false,
        language_detected: 'uz',
        transcript_quality: 'high',
      },
    },
    red_flags: [],
    outcome_signal: {
      type: 'order_agreed',
      products_mentioned: ['Bonvi paket'],
      quantity_mentioned: 50,
      confidence: 0.8,
      evidence: null,
    },
    sentiment: 'positive',
    transcript_quality: 'high',
    coaching_note: 'Narxni aytishdan oldin ehtiyojni aniqlang.',
    confidence_pct: 84,
    needs_review: false,
    review_reasons: [],
    rubric_version: 'v1',
    provider: 'anthropic',
    model: 'claude-haiku-4-5',
    prompt_tokens: 3200,
    completion_tokens: 410,
    cost_micro_usd: null,
    scored_at: '2026-09-15T10:22:00+05:00',
    ...overrides,
  }
}

/**
 * ═══════════════════════════════════════════════════════════════════════════
 * The shape the port found the hard way.
 *
 * `sales_skill` was entirely "does not apply" — a returning customer reordering
 * what they always order. The server therefore OMITS it from `blocks` while
 * `block_details.blocks` still carries it with `score: 0, applicable_max: 0`
 * for the evidence trail. A panel that iterates the second one draws a zero bar
 * for work nobody was assessed on, and the header reads "60 / 100" instead of
 * the honest "60 / 75".
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function makeScoreWithNaBlock(overrides: Partial<Score> = {}): Score {
  return makeScore({
    overall_score: 80,
    blocks: { script: 20, communication: 18, resolution: 22 },
    block_details: {
      blocks: {
        script: { score: 20, max: 25, raw_score: 12, applicable_max: 15 },
        communication: { score: 18, max: 25, raw_score: 18, applicable_max: 25 },
        resolution: { score: 22, max: 25, raw_score: 22, applicable_max: 25 },
        // Present, zero, and NOT to be drawn.
        sales_skill: { score: 0, max: 25, raw_score: 0, applicable_max: 0 },
      },
      meta: {
        blocks_total: 60,
        applicable_max: 75,
        applicable_points: 65,
        earned_points: 52,
        na_criteria: ['D1', 'D2', 'D3'],
        na_over_budget: false,
        warnings: [],
        scenario: 'repeat_order',
        penalty_total: 0,
        zeroed_by_red_flag: false,
        language_detected: 'uz',
        transcript_quality: 'high',
      },
    },
    ...overrides,
  })
}

export function makeTranscript(overrides: Partial<Transcript> = {}): Transcript {
  return {
    text:
      '[00:00] SPEAKER_0: Assalomu alaykum, Bonvi kompaniyasidan.\n' +
      '[00:04] SPEAKER_1: Vaalaykum assalom, menga oldingi buyurtmadan yana kerak.\n' +
      '[00:09] SPEAKER_0: Albatta, ellik dona qilib yuboraymi?',
    language: 'uz',
    provider: 'gemini',
    model: 'gemini-3.1-flash-lite',
    word_count: 21,
    audio_duration_ms: 184000,
    transcribed_at: '2026-09-15T10:21:30+05:00',
    ...overrides,
  }
}

export function makeCallAnalysis(overrides: Partial<CallAnalysis> = {}): CallAnalysis {
  return {
    call_id: CALL_ID,
    enabled: true,
    call: makeCallHeader(),
    state: makeState(),
    transcript: makeTranscript(),
    score: makeScore(),
    ...overrides,
  }
}

export function makeListItem(overrides: Partial<AnalysisListItem> = {}): AnalysisListItem {
  return {
    call: makeCallHeader(),
    stage: 'completed',
    failure_code: null,
    overall_score: 78,
    needs_review: false,
    red_flag_types: [],
    scored_at: '2026-09-15T10:22:00+05:00',
    ...overrides,
  }
}

export function makeListPage(
  items: AnalysisListItem[],
  overrides: Partial<AnalysisPage> = {},
): AnalysisPage {
  return { items, next_cursor: null, has_more: false, total: items.length, ...overrides }
}

export function makeStatus(overrides: Partial<AnalysisStatus> = {}): AnalysisStatus {
  return {
    enabled: true,
    stages: {
      queued: 12,
      transcribing: 1,
      scoring: 0,
      completed: 431,
      skipped: 88,
      failed: 9,
    },
    waiting_retry: 7,
    not_analysable: [
      { code: 'call_type_unknown', calls: 412 },
      { code: 'call_too_short', calls: 51 },
    ],
    cooldowns: [],
    month: {
      date_from: '2026-09-01',
      calls: 431,
      audio_minutes: 1840,
      prompt_tokens: 3120000,
      completion_tokens: 410000,
      cost_micro_usd: 0,
      priced: false,
      cap_micro_usd: 50000000,
      cap_calls: 3000,
    },
    recent_failures: [],
    ...overrides,
  }
}
