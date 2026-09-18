/**
 * The archive export — `modules/sales/export.ts`.
 *
 * What this file must not get wrong, in the order of how much damage it does:
 *
 *  1. THE CLOCK. A call at 09:14 UTC is 14:14 in Tashkent, and the panel
 *     renders Tashkent everywhere. `write-excel-file` turns a `Date` into
 *     Excel's serial through `getTime()`, so an unshifted value opens as 09:14
 *     in the file — a believable time, which is exactly why nobody would catch
 *     it, and the column a manager reads to decide whether a conversation
 *     happened before the sale;
 *  2. a missing figure must leave an EMPTY cell, never a zero. "SAP's cell was
 *     blank" and "there were no conversations" are different statements;
 *  3. the file must say what it covers — period, filter, row count — because
 *     it travels by email and loses the screen's context;
 *  4. a cut selection must SAY it was cut, or the file quietly under-reports;
 *  5. `not_checkable` is its own count on the summary sheet and is never
 *     folded into "clean".
 *
 * `buildComplianceWorkbook` is pure, so all of it is checked without a browser
 * and without loading the library.
 */
import { describe, expect, it } from 'vitest'

import {
  buildComplianceWorkbook,
  fileName,
  type ComplianceWorkbook,
  type SalesSheet,
} from '@/modules/sales/export'
import { MAX_ROWS } from '@/modules/sales/fetchAll'
import { t } from '@/shared/i18n'

import { makeItem, makeSummary } from './fixtures'

const GENERATED = new Date('2026-08-21T06:00:00Z')

function build(options: Parameters<typeof buildComplianceWorkbook>[0]): ComplianceWorkbook {
  return buildComplianceWorkbook({ generatedAt: GENERATED, ...options })
}

/**
 * A sheet by position, or a failure naming which one was missing.
 *
 * `noUncheckedIndexedAccess` is on, and a test that simply asserted on
 * `sheets[1]?.data` would pass while the summary sheet was absent — which is
 * one of the things this file is here to catch.
 */
function sheetAt(workbook: ComplianceWorkbook, index: number): SalesSheet {
  const sheet = workbook.sheets[index]
  if (!sheet) throw new Error(`the workbook has no sheet ${index}`)
  return sheet
}

function rowAt(sheet: { data: unknown[][] }, index: number): Record<string, unknown>[] {
  const row = sheet.data[index]
  if (!row) throw new Error(`the sheet has no row ${index}`)
  return row as Record<string, unknown>[]
}

/** Every cell of a sheet, flattened — for "does this text appear at all". */
function flat(data: unknown[][]): string[] {
  return data
    .flat()
    .map((cell) =>
      cell && typeof cell === 'object' && 'value' in cell ? String((cell as { value: unknown }).value) : '',
    )
    .filter(Boolean)
}

/** The header row of the sales sheet, and the row index it sits at. */
function headerRow(sheet: { data: unknown[][]; stickyRowsCount?: number }) {
  const index = (sheet.stickyRowsCount ?? 1) - 1
  return { index, cells: rowAt(sheet, index) as { value?: string }[] }
}

function cellAt(sheet: { data: unknown[][] }, row: number, column: number) {
  const cell = rowAt(sheet, row)[column]
  if (!cell) throw new Error(`the row has no cell ${column}`)
  return cell
}

describe('the sales sheet', () => {
  it('writes one row per sale, under a frozen header', () => {
    const rows = [makeItem(), makeItem({ id: 'b', external_id: '88682' })]
    const sales = sheetAt(build({ rows, summary: makeSummary() }), 0)

    const header = headerRow(sales)
    expect(header.cells[0]?.value).toBe(t('sales.col.date'))
    expect(sales.data.length).toBe(header.index + 1 + rows.length)
    // The first column is frozen too: twenty columns in, the sale's own date
    // has to stay on screen.
    expect(sales.stickyColumnsCount).toBe(1)
  })

  it('states the period, the row count and when it was downloaded', () => {
    const sales = sheetAt(
      build({
        rows: [makeItem()],
        since: '2026-07-22',
        until: '2026-08-20',
        scope: 'Doimiy mijozlar',
      }),
      0,
    )
    const head = flat(sales.data.slice(0, 6)).join(' | ')

    expect(head).toContain(t('sales.title'))
    // The "this list does not accuse anybody" sentence travels WITH the file.
    expect(head).toContain(t('sales.subtitle'))
    expect(head).toContain('22/07/2026')
    expect(head).toContain('20/08/2026')
    expect(head).toContain(t('sales.export.rows', { count: 1 }))
    expect(head).toContain('Doimiy mijozlar')
  })

  it('takes the period from the rows when the date filter is empty', () => {
    const rows = [makeItem({ occurred_on: '2026-08-12' }), makeItem({ occurred_on: '2026-07-30' })]
    const sales = sheetAt(build({ rows }), 0)
    const head = flat(sales.data.slice(0, 6)).join(' | ')

    expect(head).toContain('30/07/2026')
    expect(head).toContain('12/08/2026')
  })

  it('says so when the row cap cut the selection, and stays silent otherwise', () => {
    const cut = sheetAt(build({ rows: [makeItem()], truncated: true }), 0)
    expect(flat(cut.data.slice(0, 7)).join(' ')).toContain(
      t('sales.export.truncated', { count: MAX_ROWS }),
    )

    const whole = sheetAt(build({ rows: [makeItem()] }), 0)
    expect(flat(whole.data.slice(0, 7)).join(' ')).not.toContain(
      t('sales.export.truncated', { count: MAX_ROWS }),
    )
  })
})

describe('the clock', () => {
  it('writes a call at the Tashkent wall clock, not at UTC', () => {
    const sales = sheetAt(build({ rows: [makeItem({ last_call_at: '2026-08-03T09:14:00Z' })] }), 0)
    const header = headerRow(sales)
    const column = header.cells.findIndex((cell) => cell?.value === t('sales.col.lastCall'))
    const cell = cellAt(sales, header.index + 1, column) as { value: Date; type: unknown }

    expect(cell.type).toBe(Date)
    // 09:14 UTC is 14:14 in Tashkent, and the file must open on 14:14.
    expect((cell.value as Date).toISOString()).toBe('2026-08-03T14:14:00.000Z')
  })

  it('writes a sale date as that calendar day', () => {
    const sales = sheetAt(build({ rows: [makeItem({ occurred_on: '2026-08-12' })] }), 0)
    const header = headerRow(sales)
    const cell = cellAt(sales, header.index + 1, 0) as { value: Date }

    expect((cell.value as Date).toISOString()).toBe('2026-08-12T00:00:00.000Z')
  })

  it('writes out "never called" instead of leaving the cell blank', () => {
    const sales = sheetAt(
      build({ rows: [makeItem({ last_call_at: null, last_call_agent: null })] }),
      0,
    )
    const header = headerRow(sales)
    const column = header.cells.findIndex((cell) => cell?.value === t('sales.col.lastCall'))
    const cell = cellAt(sales, header.index + 1, column) as { value?: string }

    expect(cell.value).toBe(t('sales.noCallEver'))
  })
})

describe('an absent figure is not a zero', () => {
  it('leaves the money cell empty when SAP sent none', () => {
    const sales = sheetAt(build({ rows: [makeItem({ amount: null, amount_usd: null })] }), 0)
    const header = headerRow(sales)
    const column = header.cells.findIndex((cell) => cell?.value === t('sales.col.amountUsd'))
    const cell = cellAt(sales, header.index + 1, column) as { value?: unknown }

    expect(cell.value).toBeUndefined()
  })

  it('calls an undecided sale undecided rather than leaving it blank', () => {
    const sales = sheetAt(build({ rows: [makeItem({ review: null })] }), 0)
    const header = headerRow(sales)
    const column = header.cells.findIndex((cell) => cell?.value === t('sales.col.decision'))
    const cell = cellAt(sales, header.index + 1, column) as { value?: string }

    expect(cell.value).toBe(t('sales.review.new'))
  })

  it('names the employee-less sale instead of showing an empty column', () => {
    const sales = sheetAt(build({ rows: [makeItem({ agent_id: null, agent_name: null })] }), 0)
    const header = headerRow(sales)
    const column = header.cells.findIndex((cell) => cell?.value === t('sales.col.agent'))
    const cell = cellAt(sales, header.index + 1, column) as { value?: string }

    expect(cell.value).toBe(t('sales.noAgent'))
  })
})

describe('the summary sheet', () => {
  it('carries all three classes and the per-employee cut', () => {
    const workbook = build({ rows: [makeItem()], summary: makeSummary() })
    expect(workbook.sheets).toHaveLength(2)

    const values = flat(sheetAt(workbook, 1).data)
    expect(values).toContain(t('sales.verdict.ok'))
    // `not_checkable` is NOT a kind of `ok` — it has its own count here too.
    expect(values).toContain(t('sales.verdict.not_checkable'))
    expect(values).toContain('34')
    expect(values).toContain(t('sales.export.totalRow'))
  })

  it('is left out when the count query gave no answer', () => {
    expect(build({ rows: [makeItem()] }).sheets).toHaveLength(1)
  })
})

describe('the file name', () => {
  it('carries the period, so a folder of these files can be told apart', () => {
    expect(fileName([makeItem()], '2026-07-22', '2026-08-20', GENERATED)).toBe(
      `${t('sales.export.file')}-2026-07-22_2026-08-20.xlsx`,
    )
  })

  it('falls back to the day it was downloaded when nothing was selected', () => {
    expect(fileName([], undefined, undefined, GENERATED)).toBe(
      `${t('sales.export.file')}-2026-08-21.xlsx`,
    )
  })

  it('takes that day from the Tashkent clock, not the browser\'s', () => {
    // 20:30 UTC is already 01:30 the NEXT day in Tashkent, and every date
    // inside the file is Tashkent's.
    expect(fileName([], undefined, undefined, new Date('2026-08-21T20:30:00Z'))).toBe(
      `${t('sales.export.file')}-2026-08-22.xlsx`,
    )
  })
})
