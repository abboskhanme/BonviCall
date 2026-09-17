/**
 * Sorting the employee table — pure, and worth its own file.
 *
 * Two of the three rules below are mistakes somebody has to make once to see:
 * an absent value treated as zero, and a cached array sorted in place.
 */
import { describe, expect, it } from 'vitest'

import { sortRows } from '@/modules/activity/columns'

import { makeRow } from './fixtures'

const AZIZ = makeRow({ agent_name: 'Aziz', missed: 3, callback_rate: 50 })
const DILNOZA = makeRow({ agent_name: 'Dilnoza', missed: 9, callback_rate: 100 })
const BOBUR = makeRow({ agent_name: 'Bobur', missed: 0, callback_rate: null })

describe('sortRows', () => {
  it('keeps the server order when nothing is chosen', () => {
    const rows = [AZIZ, DILNOZA, BOBUR]
    expect(sortRows(rows, null, 'desc').map((row) => row.agent_name)).toEqual([
      'Aziz',
      'Dilnoza',
      'Bobur',
    ])
  })

  it('sorts a numeric column both ways', () => {
    const rows = [AZIZ, DILNOZA, BOBUR]
    expect(sortRows(rows, 'missed', 'desc').map((row) => row.agent_name)).toEqual([
      'Dilnoza',
      'Aziz',
      'Bobur',
    ])
    expect(sortRows(rows, 'missed', 'asc').map((row) => row.agent_name)).toEqual([
      'Bobur',
      'Aziz',
      'Dilnoza',
    ])
  })

  /**
   * ⚠️ An employee with no missed calls has NO callback rate, and there is
   * nothing to measure about them. Treated as zero they would climb to the top
   * of an ascending "worst first" list and read as the worst performer in the
   * company.
   */
  it('puts an absent value last whichever way the arrow points', () => {
    const rows = [AZIZ, DILNOZA, BOBUR]
    expect(sortRows(rows, 'rate', 'asc').map((row) => row.agent_name)).toEqual([
      'Aziz',
      'Dilnoza',
      'Bobur',
    ])
    expect(sortRows(rows, 'rate', 'desc').map((row) => row.agent_name)).toEqual([
      'Dilnoza',
      'Aziz',
      'Bobur',
    ])
  })

  /** Equal values break by name, or rows swap places on every render. */
  it('breaks a tie by name, and compares names by locale', () => {
    const rows = [
      makeRow({ agent_name: 'Хоразм', missed: 5 }),
      makeRow({ agent_name: 'Velo', missed: 5 }),
      makeRow({ agent_name: 'Sklad 10', missed: 5 }),
      makeRow({ agent_name: 'Sklad 2', missed: 5 }),
    ]
    const sorted = sortRows(rows, 'missed', 'desc').map((row) => row.agent_name)
    // `numeric` puts "Sklad 2" before "Sklad 10" rather than after it.
    expect(sorted.indexOf('Sklad 2')).toBeLessThan(sorted.indexOf('Sklad 10'))
    // A byte comparison would put every Cyrillic name in a block of its own.
    expect(sorted).toHaveLength(4)
  })

  /**
   * ⚠️ `sort()` mutates in place, and the array it is given is TanStack Query's
   * cached object. Sorting it directly corrupts the cache and another page
   * receives a different order.
   */
  it('never touches the array it was given', () => {
    const rows = [AZIZ, DILNOZA, BOBUR]
    const before = rows.map((row) => row.agent_name)
    sortRows(rows, 'missed', 'asc')
    expect(rows.map((row) => row.agent_name)).toEqual(before)
  })
})
