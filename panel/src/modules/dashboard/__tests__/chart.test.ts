/**
 * The chart's arithmetic (CONVENTIONS-CLIENT.md §10).
 *
 * Every mistake a line chart can make is a number: an axis whose top is below
 * the tallest point, a bucket drawn one step to the left, thirty date labels
 * rendered on top of each other. None of them is visible in a snapshot and all
 * of them are obvious here.
 */
import { describe, expect, it } from 'vitest'

import {
  CHART,
  bucketLabel,
  bucketTitle,
  isoDateLabel,
  labelStride,
  linePath,
  nearestIndex,
  niceMax,
  plotWidth,
  xAt,
  yAt,
  yTicks,
} from '@/modules/dashboard/chart'
import type { CallStatsBucket } from '@/modules/calls/api'

function bucket(date: string, total = 0): CallStatsBucket {
  return {
    date_from: date,
    date_to: date,
    incoming_answered: total,
    outgoing_answered: 0,
    missed: 0,
    rejected: 0,
    no_answer: 0,
    total,
  }
}

describe('the y axis', () => {
  it('never puts the tallest point on the frame', () => {
    for (const value of [1, 3, 7, 9, 23, 101, 999]) {
      expect(niceMax(value)).toBeGreaterThanOrEqual(value)
    }
  })

  it('keeps an axis for a period with no calls at all', () => {
    // Otherwise every line collapses onto the baseline and a quiet week is
    // indistinguishable from a broken chart.
    expect(niceMax(0)).toBeGreaterThan(0)
    expect(yAt(0, niceMax(0))).toBeGreaterThan(yAt(1, niceMax(0)))
  })

  it('labels every gridline with a whole number of calls', () => {
    for (const value of [1, 6, 13, 47, 260]) {
      const ticks = yTicks(niceMax(value))
      expect(ticks.every(Number.isInteger)).toBe(true)
      // Evenly spaced, which is what makes a value readable off the grid.
      expect(ticks[2]! - ticks[1]!).toBe(ticks[1]! - ticks[0]!)
    }
  })

  it('draws a bigger value lower down the page', () => {
    expect(yAt(10, 20)).toBeLessThan(yAt(5, 20))
  })
})

describe('the x axis', () => {
  it('puts the first bucket at the left edge and the last at the right', () => {
    const width = 800
    expect(xAt(0, 7, width)).toBe(CHART.padLeft)
    expect(xAt(6, 7, width)).toBe(CHART.padLeft + plotWidth(width))
  })

  it('centres a single bucket instead of pinning it to the frame', () => {
    expect(xAt(0, 1, 800)).toBeGreaterThan(CHART.padLeft)
  })

  it('thins the labels down as the card narrows', () => {
    // Thirty daily labels fit on a TV and collide on a phone (SPEC §5.2).
    expect(labelStride(30, 1600)).toBeLessThan(labelStride(30, 360))
    expect(labelStride(7, 800)).toBe(1)
  })

  it('has no dead pixel between two points', () => {
    const width = 800
    expect(nearestIndex(xAt(3, 7, width), 7, width)).toBe(3)
    expect(nearestIndex(xAt(3, 7, width) + 4, 7, width)).toBe(3)
    // Off the ends, the nearest point is still a point.
    expect(nearestIndex(-500, 7, width)).toBe(0)
    expect(nearestIndex(5000, 7, width)).toBe(6)
  })
})

describe('the line', () => {
  it('starts with a move and continues with lines', () => {
    const path = linePath([1, 2, 3], 4, 800)
    expect(path.startsWith('M ')).toBe(true)
    expect(path.match(/L /g)).toHaveLength(2)
  })

  it('draws something visible for a period of one bucket', () => {
    // A path of one point paints nothing, and "nothing" is what an empty
    // period already looks like.
    expect(linePath([2], 4, 800)).toMatch(/^M .* L /)
  })

  it('draws nothing at all when there are no buckets', () => {
    expect(linePath([], 4, 800)).toBe('')
  })
})

describe('the dates', () => {
  it('reads a calendar date without a timezone anywhere near it', () => {
    // `new Date('2026-09-15')` is midnight UTC, which renders as the 14th for
    // every reader west of Tashkent (D-10).
    expect(isoDateLabel('2026-09-15')).toBe('15.09.2026')
    expect(bucketLabel(bucket('2026-09-15'), 'day')).toBe('15.09')
    expect(bucketTitle(bucket('2026-09-15'), 'day')).toBe('15.09.2026')
  })

  it('names months in Uzbek and marks where the year rolls over', () => {
    expect(bucketLabel(bucket('2026-03-01'), 'month')).toBe('Mar')
    expect(bucketLabel(bucket('2026-01-01'), 'month')).toBe('Yan 2026')
    expect(bucketTitle(bucket('2025-10-01'), 'month')).toBe('Okt 2025')
  })
})
