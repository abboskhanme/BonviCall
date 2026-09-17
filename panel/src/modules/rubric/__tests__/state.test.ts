/**
 * The editor's arithmetic and its key derivation, without a DOM.
 *
 * These four functions decide whether the save button is alive, what a red-flag
 * key looks like and which sentence a refusal becomes. Each one is the kind of
 * logic that would otherwise sit inline in JSX, where it is only ever exercised
 * by clicking.
 */
import { describe, expect, it } from 'vitest'

import { ApiError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import {
  addCriterion,
  blockTotal,
  draftOf,
  flagKeyState,
  isDirty,
  isPublishable,
  messageOfInvalid,
  nextCriterionId,
  removeCriterion,
  replaceBlock,
  replaceCriterion,
  rubricTotal,
  slugify,
} from '@/modules/rubric/state'

import { makeRubric } from './fixtures'

const RUBRIC = makeRubric()

/** `noUncheckedIndexedAccess` is on, so every index is `T | undefined`. A test
 *  that indexes past its own fixture should fail loudly rather than compare
 *  `undefined` with `undefined` and pass. */
function at<T>(items: readonly T[], index: number): T {
  const item = items[index]
  if (item === undefined) throw new Error(`the fixture has no element at ${index}`)
  return item
}

describe('the arithmetic the server will check anyway', () => {
  it('adds a rubric up to the hundred points a score is out of', () => {
    expect(rubricTotal(RUBRIC.blocks)).toBe(100)
    expect(blockTotal(at(RUBRIC.blocks, 0))).toBe(40)
    expect(isPublishable(draftOf(RUBRIC))).toBe(true)
  })

  it('refuses to publish when the blocks do not total a hundred', () => {
    // The same 422 the server answers with, caught before the round trip: an
    // editor that let you fill the whole form first teaches people to distrust
    // the button.
    const draft = draftOf(RUBRIC)
    draft.blocks = replaceBlock(draft.blocks, 0, { label: 'Skript', max: 35 })
    expect(rubricTotal(draft.blocks)).toBe(95)
    expect(isPublishable(draft)).toBe(false)
  })

  it('refuses to publish when a block misses its own maximum', () => {
    const draft = draftOf(RUBRIC)
    draft.blocks = removeCriterion(draft.blocks, 0, 1)
    expect(rubricTotal(draft.blocks)).toBe(100)
    expect(blockTotal(at(draft.blocks, 0))).toBe(15)
    expect(isPublishable(draft)).toBe(false)
  })

  it('refuses to publish a block with no criteria left, even when the sums add up', () => {
    // Block 1 is emptied and its 35 points are moved into block 0, so the
    // rubric still totals 100 and every block still reaches its own maximum.
    // The only thing wrong is a block nothing can be scored on — which the
    // server refuses with `rubric_block_empty`, and which the arithmetic alone
    // would never notice.
    let draft = draftOf(RUBRIC)
    draft = { ...draft, blocks: removeCriterion(draft.blocks, 1, 0) }
    draft = { ...draft, blocks: replaceBlock(draft.blocks, 1, { label: 'Muomala', max: 0 }) }
    draft = {
      ...draft,
      blocks: addCriterion(draft.blocks, 0, {
        id: 'S3',
        label: 'Ko‘chirilgan ball',
        points: 35,
        description: null,
        optional: false,
      }),
    }
    draft = { ...draft, blocks: replaceBlock(draft.blocks, 0, { label: 'Skript', max: 75 }) }

    expect(rubricTotal(draft.blocks)).toBe(100)
    expect(blockTotal(at(draft.blocks, 0))).toBe(75)
    expect(isPublishable(draft)).toBe(false)
  })
})

describe('dirty tracking', () => {
  it('sees no change in an untouched draft', () => {
    expect(isDirty(draftOf(RUBRIC), RUBRIC)).toBe(false)
  })

  it('sees a change in the admin instructions, not only in the blocks', () => {
    const draft = { ...draftOf(RUBRIC), extraRules: 'yetkazib berish muddati' }
    expect(isDirty(draft, RUBRIC)).toBe(true)
  })

  it('treats null and an empty box as the same "no instructions"', () => {
    const draft = { ...draftOf(makeRubric({ extra_rules: null })), extraRules: '' }
    expect(isDirty(draft, makeRubric({ extra_rules: null }))).toBe(false)
  })
})

describe('editing without mutating', () => {
  it('leaves the original arrays alone', () => {
    const draft = draftOf(RUBRIC)
    const before = JSON.stringify(draft.blocks)

    replaceCriterion(draft.blocks, 0, 0, {
      ...at(at(draft.blocks, 0).criteria, 0),
      points: 5,
    })

    expect(JSON.stringify(draft.blocks)).toBe(before)
  })

  it('proposes the next criterion id inside its block', () => {
    expect(nextCriterionId(at(RUBRIC.blocks, 0))).toBe('S3')
    const grown = addCriterion(RUBRIC.blocks, 0, {
      id: 'S3',
      label: 'Yangi',
      points: 0,
      description: null,
      optional: false,
    })
    expect(at(grown, 0).criteria).toHaveLength(3)
    expect(at(RUBRIC.blocks, 0).criteria).toHaveLength(2)
  })
})

describe('the red-flag key', () => {
  /**
   * The key is what the model must echo back verbatim. A key with a space or a
   * capital letter makes EVERY answer fail validation — one careless save stops
   * all scoring — which is why the admin never types it.
   */
  it('turns an Uzbek label into a key the model can reproduce', () => {
    expect(slugify("Mijozni shaxsiy raqamga o'g'dirish")).toBe(
      'mijozni_shaxsiy_raqamga_ogdirish',
    )
    expect(slugify('Baqirish!')).toBe('baqirish')
    expect(slugify('  Ko‘p  gapirish  ')).toBe('kop_gapirish')
  })

  it('never produces a key longer than the column allows', () => {
    expect(slugify('a'.repeat(80))).toHaveLength(32)
  })

  it('reports a duplicate apart from an invalid key', () => {
    expect(flagKeyState('shouting', RUBRIC.red_flags)).toBe('duplicate')
    expect(flagKeyState('', RUBRIC.red_flags)).toBe('invalid')
    expect(flagKeyState('9lives', RUBRIC.red_flags)).toBe('invalid')
    expect(flagKeyState('yangi_qoida', RUBRIC.red_flags)).toBe('ok')
  })
})

describe('the server refusal, as a sentence', () => {
  it('renders the blocks-do-not-total-100 refusal with its numbers', () => {
    const error = new ApiError(422, 'validation_error', 'Validation error', {
      reason: 'rubric_total_not_100',
      total: 95,
      expected: 100,
    })

    expect(messageOfInvalid(error)).toBe(
      t('rubric.invalid.rubric_total_not_100', { total: 95, expected: 100 }),
    )
    expect(messageOfInvalid(error)).toContain('95')
  })

  it('names the block that does not add up', () => {
    const error = new ApiError(422, 'validation_error', '', {
      reason: 'rubric_block_mismatch',
      block: 'Skript',
      criteria_sum: 40,
      block_max: 50,
    })
    expect(messageOfInvalid(error)).toContain('Skript')
  })

  it('leaves an error that is not one of ours to the shared renderer', () => {
    expect(messageOfInvalid(new ApiError(403, 'forbidden', ''))).toBeNull()
    expect(messageOfInvalid(new Error('boom'))).toBeNull()
    expect(
      messageOfInvalid(new ApiError(422, 'validation_error', '', { reason: 'something_new' })),
    ).toBeNull()
  })
})
