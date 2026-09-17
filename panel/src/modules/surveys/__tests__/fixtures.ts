/**
 * Fixtures for the ratings page.
 *
 * Every figure is computed in the test from these, never read back out of a
 * response the page itself rendered (CONVENTIONS.md §13).
 */
import type { Feedback, FeedbackItem, RedFlagOption } from '../api'

export const AZIZ = '11111111-1111-4111-8111-111111111111'
export const DILNOZA = '22222222-2222-4222-8222-222222222222'

export const RED_FLAGS: RedFlagOption[] = [
  { key: 'rude', label: "Qo'pol muomala qildi" },
  { key: 'no_answer', label: "Telefonni ko'tarmadi" },
  { key: 'late_reply', label: 'Juda kech javob berdi' },
  { key: 'broken_promise', label: "Va'da berib bajarmadi" },
]

export function makeItem(overrides: Partial<FeedbackItem> = {}): FeedbackItem {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    agent_id: AZIZ,
    agent_name: 'Aziz',
    csat: 5,
    resolution: 'yes',
    comment: 'Juda yaxshi xizmat',
    red_flags: [],
    responded_at: '2026-09-15T09:00:00Z',
    ...overrides,
  }
}

/** A report that is READY — enough answers for an average to be shown. */
export function makeFeedback(overrides: Partial<Feedback> = {}): Feedback {
  return {
    average: 4.6,
    count: 5,
    ready: true,
    min_responses: 5,
    distribution: { '1': 0, '2': 0, '3': 0, '4': 2, '5': 3 },
    response_rate: 62.5,
    items_withheld: false,
    items: [
      makeItem({ id: 'a1111111-1111-4111-8111-111111111111', csat: 5 }),
      makeItem({
        id: 'a2222222-2222-4222-8222-222222222222',
        csat: 4,
        comment: null,
        resolution: 'partial',
      }),
      makeItem({
        id: 'a3333333-3333-4333-8333-333333333333',
        csat: 2,
        agent_id: DILNOZA,
        agent_name: 'Dilnoza',
        resolution: 'no',
        comment: 'Kech javob berdi',
        red_flags: ['late_reply', 'rude'],
      }),
    ],
    ...overrides,
  }
}

/** Answers have arrived, but not enough of them for an average. */
export function makeCollecting(): Feedback {
  return makeFeedback({
    average: null,
    ready: false,
    count: 3,
    min_responses: 8,
    distribution: { '1': 0, '2': 1, '3': 0, '4': 0, '5': 2 },
    response_rate: null,
    items: [makeItem()],
  })
}

/** What a salesperson gets: the summary, and nothing itemised. */
export function makeWithheld(): Feedback {
  return makeFeedback({ items: [], items_withheld: true })
}
