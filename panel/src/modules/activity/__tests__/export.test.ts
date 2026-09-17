/**
 * The Excel builder, tested WITHOUT A BROWSER.
 *
 * That is the point of `buildWorkbook` being a pure function: the file is
 * assembled client-side on purpose (so it carries exactly what is on screen),
 * and a layout nobody can test is a layout that silently rots — a merged cell
 * with no height, a percentage written as 75 instead of 0.75, a talk time that
 * wraps at 24 hours. None of those show up in a type check and all of them are
 * numbers in a file somebody forwards to a manager.
 *
 * No canvas, no library, no DOM: the picture and the download are
 * `exportActivity`'s half and are deliberately outside this file.
 */
import type { Cell, CellObject } from 'write-excel-file/browser'
import { describe, expect, it } from 'vitest'

import {
  agentsSheet,
  buildWorkbook,
  fileName,
  glossarySheet,
  seriesSheet,
  summarySheet,
  type SheetRow,
} from '@/modules/activity/export'
import { t } from '@/shared/i18n'

import { makeReport, makeRow } from './fixtures'

const META = { period: '14.08.2026 — 20.08.2026 · 7 kun', scope: '2 ta xodim', generated: 'x' }
const GENERATED_AT = new Date('2026-08-20T09:00:00Z')

/**
 * A styled cell, as opposed to a bare value or a gap.
 *
 * `Cell` is a union of `CellObject` and the four bare value types, and the
 * builders only ever emit the first — but the type has to be narrowed to read a
 * `.value` off it. A predicate rather than a cast, so a builder that starts
 * emitting bare values fails here instead of silently reading `undefined`.
 */
function isCellObject(cell: Cell): cell is CellObject {
  return typeof cell === 'object' && cell !== null && !(cell instanceof Date)
}

/** The cell at `column` of `row`, or undefined. Keeps the assertions readable. */
function cell(row: SheetRow | undefined, column: number): CellObject | undefined {
  const value = row?.[column]
  return value !== undefined && isCellObject(value) ? value : undefined
}

/** The first row whose first cell holds `value`. */
function rowStartingWith(data: SheetRow[], value: string): SheetRow | undefined {
  return data.find((row) => cell(row, 0)?.value === value)
}

describe('the workbook', () => {
  it('has the four sheets, in the order the reader needs them', () => {
    const workbook = buildWorkbook({
      report: makeReport(),
      byHour: false,
      generatedAt: GENERATED_AT,
    })
    expect(workbook.sheets.map((sheet) => sheet.sheet)).toEqual([
      t('activity.export.sheetSummary'),
      t('activity.export.sheetAgents'),
      t('activity.export.sheetDays'),
      t('activity.export.sheetGlossary'),
    ])
  })

  /** These files pile up in a folder, and nobody can tell which period
   *  `faollik(3).xlsx` belongs to. */
  it('puts the window in the file name', () => {
    expect(fileName(makeReport())).toBe(
      `${t('activity.export.file')}-2026-08-14_2026-08-20.xlsx`,
    )
  })

  it('names the third sheet after the cut that is on screen', () => {
    const hourly = buildWorkbook({
      report: makeReport({ days: 1 }),
      byHour: true,
      generatedAt: GENERATED_AT,
    })
    expect(hourly.sheets[2]?.sheet).toBe(t('activity.export.sheetHours'))
  })

  /** A grey grid makes every sheet look like a raw dump; thirteen columns in
   *  portrait split across two pages. */
  it('turns the gridlines off and prints the table in landscape', () => {
    const workbook = buildWorkbook({
      report: makeReport(),
      byHour: false,
      generatedAt: GENERATED_AT,
    })
    expect(workbook.sheets.every((sheet) => sheet.showGridLines === false)).toBe(true)
    expect(workbook.sheets[1]?.orientation).toBe('landscape')
    // Header rows and the employee's name stay put while scrolling.
    expect(workbook.sheets[1]?.stickyRowsCount).toBe(4)
    expect(workbook.sheets[1]?.stickyColumnsCount).toBe(1)
  })

  /** The picture floats above the cells, so it is anchored after the last row
   *  the summary sheet wrote. */
  it('anchors the chart below the summary block', () => {
    const summary = summarySheet(makeReport(), META)
    const workbook = buildWorkbook({
      report: makeReport(),
      byHour: false,
      generatedAt: GENERATED_AT,
    })
    expect(workbook.chartRow).toBe(summary.data.length + 1)
    expect(workbook.chartTitle).toBe(t('activity.chartTitle'))
  })
})

describe('the summary sheet', () => {
  it('carries the four headline figures the cards show', () => {
    const { data } = summarySheet(makeReport(), META)
    expect(rowStartingWith(data, t('activity.outbound'))).toBeDefined()
    expect(rowStartingWith(data, t('activity.inbound'))).toBeDefined()
    expect(rowStartingWith(data, t('activity.missed'))).toBeDefined()
    expect(cell(rowStartingWith(data, t('activity.unreached')), 1)?.value).toBe(1)
  })

  /** The median is the figure most often asked about in a presentation. */
  it('explains the median, and leaves it out when there is none', () => {
    const withMedian = summarySheet(makeReport(), META)
    expect(JSON.stringify(withMedian.data)).toContain(
      t('activity.medianNote', { minutes: 11.4, hours: 24 }),
    )

    const without = summarySheet(makeReport({ callback_median_minutes: null }), META)
    expect(JSON.stringify(without.data)).not.toContain('activity.medianNote')
  })

  /**
   * ⚠️ Excel does not auto-size a MERGED row, so a note without a height shows
   * only its first line and the rest stays inside the cell — which means the
   * report's explanations are the part nobody reads.
   */
  it('gives every merged note an explicit height', () => {
    const { data } = summarySheet(makeReport(), META)
    const merged = data
      .flat()
      .filter(isCellObject)
      .filter((item) => item.wrap === true)
    expect(merged.length).toBeGreaterThan(0)
    for (const note of merged) {
      expect(note.height ?? 0).toBeGreaterThan(0)
    }
  })
})

describe('the employee table', () => {
  it('writes one row per employee, in the order it was given', () => {
    const { data } = agentsSheet(makeReport(), META)
    const names = data.map((row) => cell(row, 0)?.value)
    expect(names).toContain('Aziz')
    expect(names).toContain('Dilnoza')
    expect(names.indexOf('Aziz')).toBeLessThan(names.indexOf('Dilnoza'))
  })

  /** "Total" inside the table: on its own sheet it would mean switching sheets
   *  to compare against it. */
  it('ends with a total row once there is more than one employee', () => {
    const { data } = agentsSheet(makeReport(), META)
    const total = rowStartingWith(data, t('activity.totalRow'))
    expect(total).toBeDefined()
    expect(cell(total, 1)?.value).toBe(50)
  })

  it('leaves the total row out for a single employee', () => {
    const one = makeReport({ agents: [makeRow()] })
    const { data } = agentsSheet(one, META)
    expect(rowStartingWith(data, t('activity.totalRow'))).toBeUndefined()
  })

  /**
   * ⚠️ NOT the average of the employees' medians. Medians cannot be averaged,
   * and this is the value the screen shows — the report's own.
   */
  it('takes the total median from the report, never from the rows', () => {
    const report = makeReport()
    const { data } = agentsSheet(report, META)
    const total = rowStartingWith(data, t('activity.totalRow'))
    expect(cell(total, 11)?.value).toBe(report.callback_median_minutes)
    // The employees' own medians are 12.5 and null; their mean is not 11.4.
    expect(cell(total, 11)?.value).not.toBe(12.5)
  })

  /** The wire carries 0-100 and Excel expects a fraction: 75 in a `0.0%` cell
   *  renders as 7500 %. */
  it('converts a percentage into the fraction Excel formats', () => {
    const { data } = agentsSheet(makeReport(), META)
    const aziz = rowStartingWith(data, 'Aziz')
    expect(cell(aziz, 7)?.value).toBeCloseTo(0.3) // missed_rate 30
    expect(cell(aziz, 10)?.value).toBeCloseTo(0.75) // callback_rate 75
  })

  /** An employee with no missed calls has no rate, and an empty cell is the
   *  right answer — a zero would read as "nobody was ever called back". */
  it('leaves an absent percentage empty rather than writing zero', () => {
    const { data } = agentsSheet(makeReport(), META)
    const dilnoza = rowStartingWith(data, 'Dilnoza')
    expect(cell(dilnoza, 10)?.value).toBeUndefined()
    expect(cell(dilnoza, 11)?.value).toBeUndefined()
  })

  /**
   * Talk time is a REAL duration, not text: Excel can then sort and sum it.
   * One hour is 3600 s, and Excel counts a day as 1.
   */
  it('writes talk time as a duration Excel can add up', () => {
    const { data } = agentsSheet(makeReport(), META)
    const aziz = rowStartingWith(data, 'Aziz')
    expect(cell(aziz, 12)?.value).toBeCloseTo(3600 / 86_400)
    // `[h]` in brackets — a plain `h` wraps at 24 hours and the total row would
    // show "31 hours 12 minutes" as "7:12".
    expect(cell(aziz, 12)?.format).toBe('[h]:mm:ss')
  })

  it('has one header cell per column', () => {
    const { data, widths } = agentsSheet(makeReport(), META)
    expect(data[3]?.length).toBe(widths.length)
    expect(widths.length).toBe(13)
  })
})

describe('the chart numbers', () => {
  /** ⚠️ `new Date('2026-08-20')` is UTC midnight, and that is what is wanted:
   *  the library converts through `getTime()`. Local midnight (UTC+5) would
   *  push the file back a day. */
  it('writes a day as a date cell at UTC midnight', () => {
    const { data } = seriesSheet(makeReport(), false)
    const first = cell(data[3], 0)
    expect(first?.type).toBe(Date)
    expect(first?.value).toEqual(new Date('2026-08-14T00:00:00.000Z'))
  })

  it('writes an hour as a label and adds the missed-rate column', () => {
    const { data } = seriesSheet(makeReport({ days: 1 }), true)
    expect(cell(data[3], 0)?.value).toBe('00:00')
    expect(data[2]?.length).toBe(7)
  })

  /** The daily cut has no rate column — the rate is an hour-of-day question. */
  it('keeps the daily cut to six columns', () => {
    const { data } = seriesSheet(makeReport(), false)
    expect(data[2]?.length).toBe(6)
  })

  it('totals the series so the sheet reconciles with the chart', () => {
    const { data } = seriesSheet(makeReport(), false)
    const total = rowStartingWith(data, t('activity.totalRow'))
    // Six days of 10 incoming plus one empty day.
    expect(cell(total, 1)?.value).toBe(60)
    expect(cell(total, 3)?.value).toBe(18)
  })

  /** Empty days are NOT removed: dropping them makes weekends disappear and
   *  the line continuous. */
  it('keeps an empty day as a row of zeroes', () => {
    const { data } = seriesSheet(makeReport(), false)
    const empty = data[4]
    expect(cell(empty, 0)?.value).toEqual(new Date('2026-08-15T00:00:00.000Z'))
    expect(cell(empty, 1)?.value).toBe(0)
  })
})

describe('the glossary', () => {
  /**
   * WHY IT EXISTS: the file travels by email and whoever opens it may never
   * have seen the screen, where each column carries its explanation. These are
   * exactly the two columns everybody confuses.
   */
  it('defines both "unanswered" columns, so they cannot be confused', () => {
    const { data } = glossarySheet(24)
    const terms = data.map((row) => cell(row, 0)?.value)
    expect(terms).toContain(t('activity.colMissed'))
    expect(terms).toContain(t('activity.colOutNoAnswer'))

    const missed = rowStartingWith(data, t('activity.colMissed'))
    expect(cell(missed, 1)?.value).toBe(t('activity.tipMissed'))
  })

  it('interpolates the callback window into the definition that needs it', () => {
    const { data } = glossarySheet(24)
    const unreached = rowStartingWith(data, t('activity.colUnreached'))
    expect(cell(unreached, 1)?.value).toBe(t('activity.tipUnreached', { hours: 24 }))
  })
})
