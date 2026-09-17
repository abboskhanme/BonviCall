/**
 * Response fixtures for the analytics tests, shaped by `types.gen.ts`.
 *
 * Typed rather than cast: a server field that is renamed or narrowed breaks
 * these first, which is the whole reason the panel's types are generated.
 *
 * Every Decimal arrives as a string, because that is what the wire carries —
 * a fixture using numbers there would let a test pass while the page renders
 * `NaN`.
 */
import type {
  AgentRanking,
  AnalyticsOverview,
  AnalyticsTimeseries,
  BlockBreakdown,
  RedFlagBreakdown,
  ScoreDistribution,
} from '@/modules/analytics/api'

export const WINDOW = { date_from: '2026-06-01', date_to: '2026-06-30' }

export function makeOverview(patch: Partial<AnalyticsOverview> = {}): AnalyticsOverview {
  return {
    ...WINDOW,
    calls: { value: 128, delta_percent: '12.5' },
    calls_total: 1420,
    call_types: { internal: 240, external: 1100, unknown: 80 },
    ai_score: { value: '78.4', delta_percent: '-3.1' },
    red_flags: { value: 9, delta_percent: '50.0' },
    avg_duration_sec: 187,
    compared_with: { date_from: '2026-05-02', date_to: '2026-05-31' },
    ...patch,
  }
}

export function makeTimeseries(
  patch: Partial<AnalyticsTimeseries> = {},
): AnalyticsTimeseries {
  return {
    ...WINDOW,
    bucket: 'day',
    filled: true,
    points: [
      { period_start: '2026-06-01', calls: 4, ai_score: '72.0' },
      { period_start: '2026-06-02', calls: 0, ai_score: null },
      { period_start: '2026-06-03', calls: 7, ai_score: '81.5' },
    ],
    ...patch,
  }
}

export function makeRanking(patch: Partial<AgentRanking> = {}): AgentRanking {
  return {
    ...WINDOW,
    total: 2,
    items: [
      {
        agent_id: '11111111-1111-4111-8111-111111111111',
        agent_name: 'Anvar Karimov',
        rank: 1,
        rank_delta: 2,
        calls: 61,
        ai_score: '88.2',
        red_flags: 1,
        avg_duration_sec: 210,
      },
      {
        agent_id: '22222222-2222-4222-8222-222222222222',
        agent_name: 'Zafar Tursunov',
        rank: 2,
        rank_delta: null,
        calls: 67,
        ai_score: '69.0',
        red_flags: 8,
        avg_duration_sec: 164,
      },
    ],
    ...patch,
  }
}

export function makeBlocks(patch: Partial<BlockBreakdown> = {}): BlockBreakdown {
  return {
    ...WINDOW,
    items: [
      { block: 'script', score: '18.5', max: 25, percent: '74.0', scored_calls: 128 },
      {
        block: 'communication',
        score: '21.0',
        max: 25,
        percent: '84.0',
        scored_calls: 128,
      },
    ],
    ...patch,
  }
}

export function makeRedFlags(patch: Partial<RedFlagBreakdown> = {}): RedFlagBreakdown {
  return {
    ...WINDOW,
    total: 9,
    items: [
      { type: 'shouting', count: 6 },
      { type: 'badmouthing', count: 3 },
    ],
    ...patch,
  }
}

export function makeDistribution(
  patch: Partial<ScoreDistribution> = {},
): ScoreDistribution {
  const floors = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
  return {
    ...WINDOW,
    scored_calls: 128,
    items: floors.map((floor) => ({
      floor,
      ceiling: floor === 90 ? 100 : floor + 9,
      calls: floor >= 60 ? 30 : 2,
    })),
    ...patch,
  }
}
