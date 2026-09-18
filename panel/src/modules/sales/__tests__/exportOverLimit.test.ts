/**
 * The over-limit workbook, tested WITHOUT A BROWSER.
 *
 * That is the point of `buildOverLimitWorkbook` being pure. This file is
 * arithmetic a manager acts on — "which tickets went over the limit and by how
 * much" — and none of the ways it can go wrong show up in a type check: a limit
 * raised in the settings turning the excess negative, a sale exactly AT the
 * limit counted as over it, an empty SAP figure written as a zero, a percentage
 * stored as 80 instead of 0.8. All of them are numbers in a file somebody
 * forwards to a director.
 *
 * ⚠️ NO `write-excel-file` IS LOADED HERE. Only its types are imported, and a
 * type import is erased at build time. The download is `exportOverLimitSales`'s
 * half and is deliberately outside this file.
 */
import type { Cell, CellObject } from 'write-excel-file/browser'
import { describe, expect, it } from 'vitest'

import { t } from '@/shared/i18n'
import { formatCount } from '@/shared/lib/format'
import { BAD, WARN } from '@/shared/lib/xlsx'

import type { ComplianceItem } from '../api'
import {
  buildOverLimitWorkbook,
  excessOf,
  glossarySheet,
  salesSheet,
  summarySheet,
  type Meta,
  type SheetRow,
} from '../exportOverLimit'

import { makeItem, makeSummary } from './fixtures'

/** The ticket limit the whole file is written against. */
const LIMIT = 500
const SINCE = '2026-07-22'
const UNTIL = '2026-08-20'
const GENERATED_AT = new Date('2026-08-20T09:00:00Z')
const META: Meta = { period: '22/07/2026 — 20/08/2026', scope: 'Bir martalik mijozlar', generated: 'x' }

/** Sheet 2: three title rows, a blank one, then the headings. */
const SALES_HEADER_ROW = 4
const SALES_FIRST_ROW = SALES_HEADER_ROW + 1
/** Sheet 3: a title, a meta line, a blank row, then the headings. */
const AGENTS_HEADER_ROW = 3
const AGENTS_FIRST_ROW = AGENTS_HEADER_ROW + 1
/** The share is the last column of the employee cut. */
const SHARE_COLUMN = 5

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

/** Which column of the sales table carries `header`. Looked up rather than
 *  hard-coded: a column inserted in the middle must not silently move the
 *  assertions onto a neighbour. */
function salesColumn(data: SheetRow[], header: string): number {
  const row = data[SALES_HEADER_ROW] ?? []
  const index = row.findIndex((value) => isCellObject(value) && value.value === header)
  expect(index).toBeGreaterThanOrEqual(0)
  return index
}

/** A walk-in sale already over the limit — what the caller hands in. */
function walkIn(overrides: Partial<ComplianceItem> = {}): ComplianceItem {
  return makeItem({
    verdict: 'not_checkable',
    broken_rules: [],
    skip_reason: 'generic_code',
    partner_code: 'К00001',
    partner_name: null,
    over_limit: true,
    amount_usd: 1_200,
    ...overrides,
  })
}

function build(rows: ComplianceItem[], overrides: Partial<Parameters<typeof buildOverLimitWorkbook>[0]> = {}) {
  return buildOverLimitWorkbook({
    rows,
    since: SINCE,
    until: UNTIL,
    limit: LIMIT,
    generatedAt: GENERATED_AT,
    ...overrides,
  })
}

describe('the workbook', () => {
  it('has the four sheets, in the order the reader needs them', () => {
    const workbook = build([walkIn()])
    expect(workbook.sheets.map((sheet) => sheet.sheet)).toEqual([
      t('sales.exportOverLimit.sheetSummary'),
      t('sales.export.sheetSales'),
      t('sales.exportOverLimit.sheetAgents'),
      t('sales.exportOverLimit.sheetGlossary'),
    ])
  })

  /** These files pile up in a folder, and nobody can tell which month
   *  `limitdan-oshgan(3).xlsx` belongs to. */
  it('puts the window in the file name', () => {
    expect(build([walkIn()]).fileName).toBe(
      `${t('sales.exportOverLimit.file')}-${SINCE}_${UNTIL}.xlsx`,
    )
  })

  it('turns the gridlines off and freezes the table headings', () => {
    const workbook = build([walkIn()])
    expect(workbook.sheets.every((sheet) => sheet.showGridLines === false)).toBe(true)
    expect(workbook.sheets[1]?.orientation).toBe('landscape')
    // Title block (3) + blank + headings, and the date column stays put.
    expect(workbook.sheets[1]?.stickyRowsCount).toBe(SALES_FIRST_ROW)
    expect(workbook.sheets[1]?.stickyColumnsCount).toBe(1)
    expect(workbook.sheets[2]?.stickyRowsCount).toBe(AGENTS_FIRST_ROW)
  })

  /** The guard against the day the server's `over_limit` filter goes missing:
   *  the file would quietly become the whole section under a title that still
   *  read "over the limit". */
  it('keeps only the sales that are over the limit', () => {
    const workbook = build([
      walkIn({ id: 'a', amount_usd: 1_200 }),
      walkIn({ id: 'b', amount_usd: 900, over_limit: false }),
    ])
    const data = workbook.sheets[1]?.data ?? []
    const amount = salesColumn(data, t('sales.col.amountUsd'))
    expect(data.length).toBe(SALES_FIRST_ROW + 1)
    expect(cell(data[SALES_FIRST_ROW], amount)?.value).toBe(1_200)
  })

  /** A manager reads this file largest-money-first; in a date-sorted list the
   *  most expensive ticket would sit somewhere in the middle. */
  it('puts the largest sale on top, whatever order the screen was in', () => {
    const workbook = build([
      walkIn({ id: 'a', amount_usd: 700 }),
      walkIn({ id: 'b', amount_usd: 2_400 }),
      walkIn({ id: 'c', amount_usd: 900 }),
    ])
    const data = workbook.sheets[1]?.data ?? []
    const amount = salesColumn(data, t('sales.col.amountUsd'))
    expect(
      data.slice(SALES_FIRST_ROW, SALES_FIRST_ROW + 3).map((row) => cell(row, amount)?.value),
    ).toEqual([2_400, 900, 700])
  })

  /** The array handed in is the page's rendered list — sorting it in place
   *  would reorder the table on screen as a side effect of pressing Export. */
  it('does not reorder the array it was handed', () => {
    const rows = [walkIn({ id: 'a', amount_usd: 700 }), walkIn({ id: 'b', amount_usd: 2_400 })]
    build(rows)
    expect(rows.map((row) => row.id)).toEqual(['a', 'b'])
  })
})

describe('the part above the limit', () => {
  /** The whole report is this subtraction. */
  it('is the amount minus the limit', () => {
    expect(excessOf(walkIn({ amount_usd: 1_200 }), LIMIT)).toBe(700)
  })

  /** A ticket AT the limit is not over it — the boundary belongs to the
   *  allowed side, and the row is in the file only because the server said so. */
  it('is zero for a sale exactly at the limit, and the cell is not coloured', () => {
    const row = walkIn({ amount_usd: LIMIT })
    expect(excessOf(row, LIMIT)).toBe(0)

    const { data } = salesSheet([row], LIMIT, META)
    const excess = cell(data[SALES_FIRST_ROW], salesColumn(data, t('sales.exportOverLimit.colExcess')))
    expect(excess?.value).toBe(0)
    expect(excess?.textColor).toBeUndefined()
  })

  /** The limit lives in the settings and can be raised after a list was
   *  fetched. Without the clamp the cell would read "−300 $ over the limit". */
  it('never goes negative when the limit was raised after the fact', () => {
    expect(excessOf(walkIn({ amount_usd: 200 }), LIMIT)).toBe(0)
  })

  /** Two levels, because they call for two different actions: a little over is
   *  an ordinary large purchase, twice over is nearly always a regular
   *  customer written under the wrong code. */
  it('colours a little over amber and twice over red', () => {
    const { data } = salesSheet(
      [walkIn({ id: 'a', amount_usd: 1_400 }), walkIn({ id: 'b', amount_usd: 700 })],
      LIMIT,
      META,
    )
    const excess = salesColumn(data, t('sales.exportOverLimit.colExcess'))
    expect(cell(data[SALES_FIRST_ROW], excess)?.textColor).toBe(BAD)
    expect(cell(data[SALES_FIRST_ROW + 1], excess)?.textColor).toBe(WARN)
  })

  /** "SAP's cell was empty" and "this sale was worth nothing" are different
   *  statements, and only one of them is ever true. */
  it('leaves an absent amount EMPTY rather than writing a zero', () => {
    const row = walkIn({ amount: null, amount_usd: null })
    expect(excessOf(row, LIMIT)).toBeNull()

    const { data } = salesSheet([row], LIMIT, META)
    const cells = data[SALES_FIRST_ROW]
    expect(cell(cells, salesColumn(data, t('sales.col.amountUsd')))?.value).toBeUndefined()
    expect(cell(cells, salesColumn(data, t('sales.exportOverLimit.colExcess')))?.value).toBeUndefined()
  })

  /** The total is inside the table, and an empty figure must not poison it. */
  it('totals the column past the empty figures', () => {
    const { data } = salesSheet(
      [walkIn({ id: 'a', amount_usd: 1_200 }), walkIn({ id: 'b', amount_usd: null })],
      LIMIT,
      META,
    )
    const total = data[data.length - 1]
    expect(cell(total, 0)?.value).toBe(t('sales.export.totalRow'))
    expect(cell(total, salesColumn(data, t('sales.col.amountUsd')))?.value).toBe(1_200)
    expect(cell(total, salesColumn(data, t('sales.exportOverLimit.colExcess')))?.value).toBe(700)
  })

  it('leaves the total row out for a single sale', () => {
    const { data } = salesSheet([walkIn()], LIMIT, META)
    expect(data.length).toBe(SALES_FIRST_ROW + 1)
  })
})

describe('the sales table', () => {
  /** SAP gives a sale no clock, and `occurred_on` must land on its own
   *  calendar day whatever zone the reader sits in (`saleDate.ts`). */
  it('writes the sale day as a date cell at UTC midnight', () => {
    const { data } = salesSheet([walkIn({ occurred_on: '2026-08-12' })], LIMIT, META)
    const value = cell(data[SALES_FIRST_ROW], salesColumn(data, t('sales.col.date')))?.value
    expect(value).toBeInstanceOf(Date)
    expect(value).toEqual(new Date('2026-08-12'))
  })

  /** For a walk-in buyer "no conversation at all" is the ORDINARY case, so it
   *  is written out in words — and not in red. */
  it('says so when there was never a call, instead of leaving a gap', () => {
    const { data } = salesSheet([walkIn({ last_call_at: null })], LIMIT, META)
    const value = cell(data[SALES_FIRST_ROW], salesColumn(data, t('sales.col.lastCall')))
    expect(value?.value).toBe(t('sales.noCallEver'))
    expect(value?.textColor).not.toBe(BAD)
  })

  /** The decision comes from `REVIEW_LABEL`, not from a built key. */
  it('names the decision, and calls an undecided sale undecided', () => {
    const { data } = salesSheet(
      [
        walkIn({ id: 'a', amount_usd: 2_000, review: { status: 'justified', reason: 'walk_in' } }),
        walkIn({ id: 'b', amount_usd: 1_000, review: null }),
      ],
      LIMIT,
      META,
    )
    const decision = salesColumn(data, t('sales.col.decision'))
    expect(cell(data[SALES_FIRST_ROW], decision)?.value).toBe(t('sales.review.justified'))
    expect(cell(data[SALES_FIRST_ROW + 1], decision)?.value).toBe(t('sales.review.new'))
  })

  /** SAP's `Подразделение` IS the employee, so an unlinked sale prints SAP's
   *  own word in the warning tone rather than nothing: some branches are
   *  unlinked ON PURPOSE and a blank cell would read as a fault. */
  it('never leaves the employee blank', () => {
    const { data } = salesSheet(
      [
        walkIn({ id: 'a', amount_usd: 2_000, agent_id: null, agent_name: null, branch: 'Нукус' }),
        walkIn({ id: 'b', amount_usd: 1_000, agent_id: null, agent_name: null, branch: null }),
      ],
      LIMIT,
      META,
    )
    const agent = salesColumn(data, t('sales.col.agent'))
    expect(cell(data[SALES_FIRST_ROW], agent)?.value).toBe('Нукус')
    expect(cell(data[SALES_FIRST_ROW], agent)?.textColor).toBe(WARN)
    expect(cell(data[SALES_FIRST_ROW + 1], agent)?.value).toBe(t('sales.noAgent'))
  })
})

describe('the employee cut', () => {
  /** The shares are what a manager reads first; they have to close on 100 %. */
  it('gives every employee a share, and they add up to 100 %', () => {
    const workbook = build([
      walkIn({ id: 'a', agent_id: 'one', agent_name: 'Zuhriddin Rasulov', amount_usd: 1_200 }),
      walkIn({ id: 'b', agent_id: 'two', agent_name: 'Dilshod Qodirov', amount_usd: 800 }),
    ])
    const data = workbook.sheets[2]?.data ?? []

    const shares = [AGENTS_FIRST_ROW, AGENTS_FIRST_ROW + 1].map((index) =>
      Number(cell(data[index], SHARE_COLUMN)?.value),
    )
    // `pct` stores the fraction Excel formats, not the 0-100 number.
    expect(shares).toEqual([0.6, 0.4])
    expect(shares.reduce((acc, share) => acc + share, 0)).toBeCloseTo(1, 10)

    const total = data[AGENTS_FIRST_ROW + 2]
    expect(cell(total, 0)?.value).toBe(t('sales.export.totalRow'))
    expect(cell(total, SHARE_COLUMN)?.value).toBe(1)
  })

  /** The server's own cut merges every unlinked branch into one line, and this
   *  sheet has to reconcile with it. */
  it('collects the sales with no employee under one named line', () => {
    const workbook = build([
      walkIn({ id: 'a', agent_id: null, agent_name: null, branch: 'Нукус', amount_usd: 1_200 }),
      walkIn({ id: 'b', agent_id: null, agent_name: null, branch: 'Логистика', amount_usd: 800 }),
    ])
    const data = workbook.sheets[2]?.data ?? []
    expect(cell(data[AGENTS_FIRST_ROW], 0)?.value).toBe(t('sales.noAgent'))
    expect(cell(data[AGENTS_FIRST_ROW], 1)?.value).toBe(2)
    expect(cell(data[AGENTS_FIRST_ROW], 2)?.value).toBe(2_000)
  })

  /**
   * ⚠️ The summary is computed over the SCOPE, the list follows the review
   * filter on screen. Unstated, the two numbers make the file contradict
   * itself and the blame lands on the report.
   */
  it('writes the difference out when the summary counts more than the list', () => {
    const summary = makeSummary({
      walk_in_limit: LIMIT,
      over_limit: 3,
      over_limit_amount: 2_400,
      agents: [
        {
          agent_id: 'one',
          agent_name: 'Zuhriddin Rasulov',
          sales: 120,
          ok: 0,
          suspicious: 0,
          not_checkable: 120,
          new: 0,
          justified: 0,
          confirmed: 0,
          over_limit: 3,
          over_limit_amount: 2_400,
        },
      ],
    })
    const workbook = build(
      [
        walkIn({ id: 'a', agent_id: 'one', agent_name: 'Zuhriddin Rasulov', amount_usd: 1_600 }),
        walkIn({ id: 'b', agent_id: 'one', agent_name: 'Zuhriddin Rasulov', amount_usd: 800 }),
      ],
      { summary },
    )
    const data = workbook.sheets[2]?.data ?? []

    // The count and the amount come from the summary, the largest from the rows.
    expect(cell(data[AGENTS_FIRST_ROW], 1)?.value).toBe(3)
    expect(cell(data[AGENTS_FIRST_ROW], 2)?.value).toBe(2_400)
    expect(cell(data[AGENTS_FIRST_ROW], 4)?.value).toBe(1_600)

    expect(
      rowStartingWith(data, t('sales.exportOverLimit.mismatch', { summary: 3, rows: 2 })),
    ).toBeDefined()
  })

  it('stays quiet when the two counts agree', () => {
    const summary = makeSummary({
      walk_in_limit: LIMIT,
      over_limit: 1,
      over_limit_amount: 1_600,
      agents: [
        {
          agent_id: 'one',
          agent_name: 'Zuhriddin Rasulov',
          sales: 120,
          ok: 0,
          suspicious: 0,
          not_checkable: 120,
          new: 0,
          justified: 0,
          confirmed: 0,
          over_limit: 1,
          over_limit_amount: 1_600,
        },
      ],
    })
    const workbook = build(
      [walkIn({ id: 'a', agent_id: 'one', agent_name: 'Zuhriddin Rasulov', amount_usd: 1_600 })],
      { summary },
    )
    const data = workbook.sheets[2]?.data ?? []
    // One employee: one line, no total row of its own, and nothing after it.
    expect(data.length).toBe(AGENTS_FIRST_ROW + 1)
  })
})

describe('the limit the file was built against', () => {
  /**
   * The setting can be changed tomorrow and nothing recomputes an old file, so
   * the file has to state its own basis — as a figure, and again in words.
   */
  it('is printed as a headline figure on the summary sheet', () => {
    const { data } = summarySheet([walkIn()], undefined, LIMIT, META)
    const row = rowStartingWith(data, t('sales.exportOverLimit.limit'))
    expect(cell(row, 1)?.value).toBe(LIMIT)
    expect(cell(row, 2)?.value).toBe(t('sales.exportOverLimit.limitSource'))
    expect(rowStartingWith(data, t('sales.exportOverLimit.title'))).toBeDefined()
  })

  it('is spelled out again in the glossary', () => {
    const { data } = glossarySheet(1_500)
    const row = rowStartingWith(data, t('sales.exportOverLimit.termLimit'))
    expect(cell(row, 1)?.value).toBe(
      t('sales.exportOverLimit.defLimit', { limit: formatCount(1_500) }),
    )
  })

  /** Every merged note needs an explicit height: Excel does not auto-fit one,
   *  so without it only the first line of the longest explanation is visible. */
  it('gives the merged notes under it an explicit height', () => {
    const { data } = summarySheet([walkIn()], undefined, LIMIT, META)
    const note = rowStartingWith(data, t('sales.exportOverLimit.walkInNote'))
    expect(cell(note, 0)?.height).toBeGreaterThan(15)
    expect(cell(note, 0)?.wrap).toBe(true)
  })

  /** The denominator is the context: 6 out of 843 and 200 out of 843 are
   *  entirely different messages. */
  it('states how many walk-in sales the count is out of', () => {
    const summary = makeSummary({ total: 718, walk_in_limit: LIMIT })
    const { data } = summarySheet([walkIn()], summary, LIMIT, META)
    const row = rowStartingWith(data, t('sales.exportOverLimit.count'))
    expect(cell(row, 1)?.value).toBe(1)
    expect(cell(row, 2)?.value).toBe(t('sales.exportOverLimit.countOf', { total: 718 }))
  })
})
