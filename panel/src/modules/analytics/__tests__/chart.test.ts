/**
 * The analytics chart arithmetic (`modules/analytics/chart.ts`).
 *
 * Everything that could be *wrong* about a chart on this page is in here: the
 * Decimal-to-number conversion the whole page depends on, the null that must
 * stay a gap rather than become a zero, the band colours and the period labels.
 * The components themselves are declarative and are covered by the page test.
 */
import { describe, expect, it } from 'vitest'

import {
  CHART_COLOR,
  bandOf,
  blockRows,
  bucketColor,
  bucketLabel,
  deltaIsGood,
  periodLabel,
  toCount,
  toNumber,
  trendRows,
} from '@/modules/analytics/chart'

import { makeBlocks, makeTimeseries } from './fixtures'

describe('the Decimal the wire carries', () => {
  it('reads a NUMERIC string as a number a chart can scale', () => {
    expect(toNumber('78.4')).toBe(78.4)
    expect(toNumber('0.0')).toBe(0)
    expect(toNumber('-3.1')).toBe(-3.1)
  })

  /**
   * A period with nothing scored has no average, and plotting it as 0 would
   * drag the trend line down through a quiet day as though the team had scored
   * zero. `connectNulls` is off on that series for the same reason.
   */
  it('keeps "nothing was scored" as a gap rather than a zero', () => {
    expect(toNumber(null)).toBeNull()
    expect(toNumber(undefined)).toBeNull()
    expect(toNumber('')).toBeNull()
  })

  it('refuses a value that is not a number at all', () => {
    expect(toNumber('n/a')).toBeNull()
  })

  it('counts a missing value as zero where a count is what is asked', () => {
    expect(toCount(null)).toBe(0)
    expect(toCount('9')).toBe(9)
  })
})

describe('the score bands', () => {
  it('uses the same four boundaries as the list page', () => {
    expect(bandOf(85)).toBe('excellent')
    expect(bandOf(84)).toBe('good')
    expect(bandOf(70)).toBe('good')
    expect(bandOf(69)).toBe('average')
    expect(bandOf(55)).toBe('average')
    expect(bandOf(54)).toBe('poor')
  })

  it('colours a histogram band from a CSS token, never a hex literal', () => {
    expect(bucketColor(90)).toBe(CHART_COLOR.good)
    expect(bucketColor(70)).toBe(CHART_COLOR.accent)
    expect(bucketColor(60)).toBe(CHART_COLOR.warn)
    expect(bucketColor(0)).toBe(CHART_COLOR.bad)
    // The mechanism, stated as an assertion: every colour is a token
    // expression the browser resolves against index.css, so the charts follow
    // light, dark and system themes without a `dark:` variant.
    for (const colour of Object.values(CHART_COLOR)) {
      expect(colour).toMatch(/^hsl\(var\(--[a-z0-9-]+\)\)$/)
    }
  })

  it('labels a band as a range with an en dash', () => {
    expect(bucketLabel({ floor: 80, ceiling: 89 })).toBe('80–89')
    expect(bucketLabel({ floor: 90, ceiling: 100 })).toBe('90–100')
  })
})

describe('the trend rows', () => {
  it('labels a daily bucket dd/mm and a monthly one mm/yyyy', () => {
    expect(periodLabel('2026-06-03', 'day')).toBe('03/06')
    expect(periodLabel('2026-06-01', 'week')).toBe('01/06')
    expect(periodLabel('2026-06-01', 'month')).toBe('06/2026')
  })

  /**
   * Built from the ISO string and never from a `Date`: `period_start` is an
   * Asia/Tashkent calendar date the server already decided, and re-reading it
   * in the browser's zone would move a bucket by a day for anybody west of us.
   */
  it('does not re-interpret a server date in the browser zone', () => {
    expect(periodLabel('2026-01-01', 'month')).toBe('01/2026')
  })

  it('converts every score once and keeps the quiet day empty', () => {
    const rows = trendRows(makeTimeseries().points, 'day')
    expect(rows.map((row) => row.ai_score)).toEqual([72, null, 81.5])
    expect(rows.map((row) => row.calls)).toEqual([4, 0, 7])
    expect(rows.map((row) => row.label)).toEqual(['01/06', '02/06', '03/06'])
  })
})

describe('the radar rows', () => {
  it('plots the percentage and keeps the points for the tooltip', () => {
    const rows = blockRows(makeBlocks().items, (key) => `label:${key}`)
    expect(rows).toEqual([
      { block: 'script', label: 'label:script', percent: 74, score: 18.5, max: 25 },
      {
        block: 'communication',
        label: 'label:communication',
        percent: 84,
        score: 21,
        max: 25,
      },
    ])
  })
})

describe('whether a change is good news', () => {
  it('reads a rise as good by default', () => {
    expect(deltaIsGood(12.5)).toBe(true)
    expect(deltaIsGood(-3.1)).toBe(false)
  })

  /**
   * Without this the breaches card turns green in the week somebody shouted at
   * four customers.
   */
  it('reads a rise in breaches as bad news', () => {
    expect(deltaIsGood(50, true)).toBe(false)
    expect(deltaIsGood(-50, true)).toBe(true)
  })

  it('has no opinion about no change, or about no comparison at all', () => {
    expect(deltaIsGood(0)).toBeNull()
    expect(deltaIsGood(null)).toBeNull()
  })
})
