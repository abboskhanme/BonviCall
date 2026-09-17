/**
 * Rubric fixtures, shaped by the generated types.
 *
 * `Rubric` and friends come from `types.gen.ts`, so a field the server renames
 * breaks these files at compile time instead of leaving the tests asserting
 * against a shape that no longer exists.
 *
 * The blocks total exactly 100 — 40 + 35 + 25 — because that is the one rule
 * the server enforces, and a fixture that quietly broke it would make every
 * "the save button is enabled" assertion meaningless.
 */
import type {
  Rubric,
  RubricPrompt,
  RubricVersions,
} from '@/modules/rubric/api'

export const RUBRIC_ID = '11111111-1111-4111-8111-111111111111'

export function makeRubric(overrides: Partial<Rubric> = {}): Rubric {
  return {
    id: RUBRIC_ID,
    version: 1,
    label: 'v1',
    name: 'Mezonlar v1',
    description: null,
    is_active: true,
    stored: true,
    blocks: [
      {
        key: 'script',
        label: 'Skript',
        max: 40,
        criteria: [
          {
            id: 'A1',
            label: 'Salomlashish',
            points: 15,
            description: 'Xushmuomala salomlashish',
            optional: false,
          },
          {
            id: 'A2',
            label: 'Ehtiyojni aniqlash',
            points: 25,
            description: null,
            optional: true,
          },
        ],
      },
      {
        key: 'manner',
        label: 'Muomala',
        max: 35,
        criteria: [
          { id: 'B1', label: 'Hurmatli ohang', points: 35, description: null, optional: false },
        ],
      },
      {
        key: 'closing',
        label: 'Yakun',
        max: 25,
        criteria: [
          { id: 'C1', label: 'Keyingi qadam', points: 25, description: null, optional: false },
        ],
      },
    ],
    red_flags: [
      {
        type: 'profanity',
        label: 'Haqorat',
        penalty: -100,
        zeroes_score: true,
        description: null,
      },
      {
        type: 'shouting',
        label: 'Baqirish',
        penalty: -20,
        zeroes_score: false,
        description: null,
      },
    ],
    extra_rules: null,
    extra_rules_limit: 4000,
    created_at: '2026-09-17T10:00:00+05:00',
    ...overrides,
  }
}

export function makeVersions(overrides: Partial<RubricVersions> = {}): RubricVersions {
  return {
    items: [
      {
        version: 2,
        label: 'v2',
        name: 'Mezonlar v2',
        is_active: true,
        created_at: '2026-09-17T11:00:00+05:00',
      },
      {
        version: 1,
        label: 'v1',
        name: 'Mezonlar v1',
        is_active: false,
        created_at: '2026-09-01T09:00:00+05:00',
      },
    ],
    total: 2,
    ...overrides,
  }
}

export function makePrompt(overrides: Partial<RubricPrompt> = {}): RubricPrompt {
  return {
    rubric_version: 1,
    rubric_label: 'v1',
    sections: [
      { key: 'intro', editable: false, text: 'Siz — savdo sifati auditorisiz.' },
      { key: 'extra_rules', editable: true, text: 'Yetkazib berish muddatini so’rang.' },
      { key: 'format', editable: false, text: 'Faqat JSON qaytaring.' },
    ],
    full_text: 'Siz — savdo sifati auditorisiz.',
    char_count: 12_982,
    approx_tokens: 3_934,
    extra_rules_limit: 4000,
    ...overrides,
  }
}
