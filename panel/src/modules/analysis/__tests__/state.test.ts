/**
 * The four decisions of §7.4 that go wrong silently, pinned.
 *
 *  1. the precedence table — **in order**. Every row is asserted, and so is the
 *     ordering itself: the two flag-off rows are tested against inputs that
 *     also satisfy a row below them, which is the only way a test can tell an
 *     ordered list from an unordered set.
 *  2. the "not applicable" block — the rendering rule the port found the hard
 *     way, in both directions: the bar is absent, and the header is honest.
 *  3. `priced: false` never becoming "$0.00".
 *  4. review reasons rendering from a code and params, never from stored copy.
 */
import { describe, expect, it } from 'vitest'

import { t } from '@/shared/i18n'
import {
  analysisView,
  blockRows,
  formatMicroUsd,
  monthCost,
  reviewReasonText,
  scoreTotals,
  speakerLane,
  speakerOrder,
  transcriptLines,
} from '@/modules/analysis/state'
import { bandOf } from '@/modules/analysis/labels'
import {
  makeCallAnalysis,
  makeScore,
  makeScoreWithNaBlock,
  makeState,
  makeStatus,
} from './fixtures'

describe('the §7.4 precedence list', () => {
  it('shows only "Tahlil o\'chirilgan" when the flag is off and nothing was analysed', () => {
    const view = analysisView(makeCallAnalysis({ enabled: false, state: null, score: null, transcript: null }))
    expect(view).toEqual({ kind: 'disabled', offersRun: false, readOnly: false })
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * The row that proves the table is ORDERED.
   *
   * This input satisfies row 7 ("completed") as well, and a reader who takes
   * the table as an unordered set lands there — rendering the score with a
   * button that would answer 409 `analysis_disabled`. Row 2 wins because it is
   * written above it: the rows are shown, the button is not.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('shows existing rows read-only when the flag is off, with no button', () => {
    const view = analysisView(makeCallAnalysis({ enabled: false }))
    expect(view).toEqual({ kind: 'completed', offersRun: false, readOnly: true })
  })

  it('offers no button on a FAILED call either while the flag is off', () => {
    // The other half of the same trap: `failed` is the one stage that normally
    // carries a retry, and the flag being off outranks it.
    const view = analysisView(
      makeCallAnalysis({
        enabled: false,
        state: makeState({ stage: 'failed', failure_code: 'provider_network' }),
      }),
    )
    expect(view.kind).toBe('failed')
    expect(view.offersRun).toBe(false)
    expect(view.readOnly).toBe(true)
  })

  it('offers the run button when there is no state row at all', () => {
    const view = analysisView(
      makeCallAnalysis({ state: null, score: null, transcript: null }),
    )
    expect(view).toEqual({ kind: 'not_analysed', offersRun: true, readOnly: false })
  })

  it.each(['queued', 'transcribing', 'scoring'] as const)(
    'treats %s as a running stage, with nothing to press',
    (stage) => {
      const view = analysisView(
        makeCallAnalysis({ state: makeState({ stage }), score: null, transcript: null }),
      )
      expect(view.kind).toBe('running')
      expect(view.offersRun).toBe(false)
    },
  )

  /**
   * ══════════════════════════════════════════════════════════════════════
   * `skipped` is not a failure and must not grow a retry button.
   *
   * A skipped call failed the §2.6 gate — no audio, too short, not an external
   * answered call — and none of those repairs itself by being asked again. The
   * button would answer 409 `call_not_analysable` on every single press.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('offers nothing on a skipped call', () => {
    const view = analysisView(
      makeCallAnalysis({
        state: makeState({ stage: 'skipped', failure_code: 'no_audio' }),
        score: null,
        transcript: null,
      }),
    )
    expect(view).toEqual({ kind: 'skipped', offersRun: false, readOnly: false })
  })

  it('offers the retry button on a failed call', () => {
    const view = analysisView(
      makeCallAnalysis({
        state: makeState({
          stage: 'failed',
          failure_code: 'provider_rate_limit',
          failure_stage: 'transcribe',
          failure_detail: 'HTTP 429',
        }),
        score: null,
        transcript: null,
      }),
    )
    expect(view).toEqual({ kind: 'failed', offersRun: true, readOnly: false })
  })

  /**
   * Re-scoring needs `force: true`, which is the only way to spend money twice
   * on one call (§6.2), and §7.4 puts no such control on this page. A button
   * here would be a second bill one click away from every completed score.
   */
  it('offers no button on a completed call', () => {
    const view = analysisView(makeCallAnalysis())
    expect(view).toEqual({ kind: 'completed', offersRun: false, readOnly: false })
  })
})

describe('the score block', () => {
  it('draws one bar per assessed block, in the rubric order', () => {
    expect(blockRows(makeScore()).map((row) => row.key)).toEqual([
      'script',
      'communication',
      'resolution',
      'sales_skill',
    ])
  })

  it('takes each bar\'s denominator from block_details, never from a constant', () => {
    expect(blockRows(makeScore())).toEqual([
      { key: 'script', score: 20, max: 25 },
      { key: 'communication', score: 18, max: 25 },
      { key: 'resolution', score: 22, max: 25 },
      { key: 'sales_skill', score: 18, max: 25 },
    ])
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * The rule this file exists for.
   *
   * A block whose criteria were ALL "does not apply" is absent from `blocks`
   * and present in `block_details.blocks` with `score: 0`. Reading the wrong
   * one draws a zero bar for work nobody was assessed on — which, in front of
   * a manager, says the employee failed a quarter of the call.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('never draws a bar for a block nobody was assessed on', () => {
    const rows = blockRows(makeScoreWithNaBlock())
    expect(rows.map((row) => row.key)).toEqual(['script', 'communication', 'resolution'])
    expect(rows.some((row) => row.key === 'sales_skill')).toBe(false)
    expect(rows.some((row) => row.score === 0)).toBe(false)
  })

  it('drops a zero block even if it somehow reaches the flat map', () => {
    // Belt and braces for a hand-edited row: `applicable_max: 0` is the fact,
    // and it wins over the key's presence in `blocks`.
    const score = makeScoreWithNaBlock({
      blocks: { script: 20, communication: 18, resolution: 22, sales_skill: 0 },
    })
    expect(blockRows(score).map((row) => row.key)).not.toContain('sales_skill')
  })

  it('reads the header "60 / 75" out of meta rather than assuming 100', () => {
    expect(scoreTotals(makeScoreWithNaBlock())).toEqual({ earned: 60, max: 75, naCount: 3 })
  })

  it('reads a full rubric as 78 / 100 with nothing marked inapplicable', () => {
    expect(scoreTotals(makeScore())).toEqual({ earned: 78, max: 100, naCount: 0 })
  })

  it('prints no fraction at all when the document carries no applicable_max', () => {
    // Never a guessed denominator: a bar drawn against an invented maximum is
    // how a 167 % bar once reached a manager.
    const score = makeScore({ block_details: {} })
    expect(scoreTotals(score).max).toBeNull()
    // The earned figure still falls back to the blocks it does have.
    expect(scoreTotals(score).earned).toBe(78)
    expect(blockRows(score).every((row) => row.max === null)).toBe(true)
  })

  it('bands a score by the server\'s own thresholds', () => {
    expect(bandOf(100)).toBe('excellent')
    expect(bandOf(85)).toBe('excellent')
    expect(bandOf(84)).toBe('good')
    expect(bandOf(70)).toBe('good')
    expect(bandOf(69)).toBe('average')
    expect(bandOf(55)).toBe('average')
    expect(bandOf(54)).toBe('poor')
    expect(bandOf(0)).toBe('poor')
  })
})

describe('review reasons', () => {
  it('renders the Uzbek sentence from the code and its params', () => {
    const text = reviewReasonText({
      code: 'low_confidence',
      params: { confidence_pct: 61, threshold: 70 },
    })
    expect(text).toBe(t('analysis.review.low_confidence', { confidence_pct: 61, threshold: 70 }))
    expect(text).toContain('61')
    expect(text).toContain('70')
    // The column holds a machine reason and never display copy (§1.6).
    expect(text).not.toContain('low_confidence')
  })

  it('names the breaches rather than their identifiers', () => {
    const text = reviewReasonText({
      code: 'red_flag',
      params: { types: ['shouting', 'badmouthing'] },
    })
    expect(text).toContain(t('analysis.redFlag.shouting'))
    expect(text).toContain(t('analysis.redFlag.badmouthing'))
    expect(text).not.toContain('shouting')
  })

  it('renders a code it does not know rather than a blank line', () => {
    expect(reviewReasonText({ code: 'invented_by_phase_2', params: {} })).toBe(
      'invented_by_phase_2',
    )
  })
})

describe('the month, and why zero is not a number to print', () => {
  it('refuses to render a cost while no vendor price has been entered', () => {
    // `cost_micro_usd: 0` with `priced: false` is "nobody typed a price", not
    // "the feature is free" — and $0.00 is how a client concludes the latter.
    const cost = monthCost(makeStatus().month)
    expect(cost.text).toBeNull()
    expect(cost.cap).toBeNull()
  })

  it('renders both the spend and the cap once a price exists', () => {
    const month = { ...makeStatus().month, priced: true, cost_micro_usd: 12_340_000 }
    expect(monthCost(month)).toEqual({ text: '$12.34', cap: '$50.00' })
  })

  it('converts micro-USD without losing the cents', () => {
    expect(formatMicroUsd(0)).toBe('$0.00')
    expect(formatMicroUsd(1_000_000)).toBe('$1.00')
    expect(formatMicroUsd(1_500)).toBe('$0.00')
    expect(formatMicroUsd(1_234_567)).toBe('$1.23')
  })
})

describe('the transcript', () => {
  const TEXT =
    '[00:00] SPEAKER_0: Assalomu alaykum.\n' +
    '[00:04] SPEAKER_1: Vaalaykum assalom.\n' +
    '\n' +
    'Nomsiz qator.'

  it('splits a line into its timestamp, speaker and words', () => {
    const lines = transcriptLines(TEXT)
    expect(lines).toHaveLength(3)
    expect(lines[0]).toEqual({
      timestamp: '[00:00]',
      speaker: 'SPEAKER_0',
      text: 'Assalomu alaykum.',
    })
    // A line with neither marker is still a line, not a dropped one.
    expect(lines[2]).toEqual({ timestamp: null, speaker: null, text: 'Nomsiz qator.' })
  })

  it('gives the two speakers two lanes, and a third no lane of its own', () => {
    const lines = transcriptLines(TEXT)
    const order = speakerOrder(lines)
    expect(order).toEqual(['SPEAKER_0', 'SPEAKER_1'])
    expect(speakerLane('SPEAKER_0', order)).toBe(0)
    expect(speakerLane('SPEAKER_1', order)).toBe(1)
    expect(speakerLane('SPEAKER_2', order)).toBe(1)
    expect(speakerLane(null, order)).toBe(0)
  })

  it('drops blank lines rather than rendering empty rows', () => {
    expect(transcriptLines('\n\n   \n').length).toBe(0)
  })
})
