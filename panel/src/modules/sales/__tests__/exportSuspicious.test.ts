/**
 * The suspicious-sales report — `modules/sales/exportSuspicious.ts`.
 *
 * This file is READ by a manager rather than reconciled by a clerk, and it
 * travels by email, so what it must not get wrong is what it ASSERTS:
 *
 *  1. the figures on "Xulosa" are counted from the rows in the file, never
 *     from the summary — two sources in one file make it contradict itself
 *     ("40 rows in the table, 57 decisions in the heading");
 *  2. an empty selection must say "nothing was found" as a RESULT. A sheet
 *     holding only its heading looks like a fault, and a total row under no
 *     rows is worse;
 *  3. a missing figure leaves an EMPTY cell, never a zero. "We could not know"
 *     and "there were none" are different statements and only one is true;
 *  4. the timeline's order is the SERVER's. On one day the call comes before
 *     the sale, which is how the rules compute; a sale's `at` is 00:00 of its
 *     day, so any re-sort here would quietly invert it;
 *  5. a cut timeline must SAY it was cut, or a customer missing from the sheet
 *     reads as a customer with nothing against them.
 *
 * `buildSuspiciousWorkbook` is pure, so all of it is checked without a browser
 * and WITHOUT loading `write-excel-file` — which is the point of the dynamic
 * import in the module under test.
 */
import { describe, expect, it } from 'vitest'

import { buildSuspiciousWorkbook, fileName } from '@/modules/sales/exportSuspicious'
import { t } from '@/shared/i18n'

import { makeItem, makeSummary, makeTimeline } from './fixtures'

const GENERATED = new Date('2026-08-21T06:00:00Z')

type Options = Parameters<typeof buildSuspiciousWorkbook>[0]
type Workbook = ReturnType<typeof buildSuspiciousWorkbook>
type Sheet = Workbook['sheets'][number]

function build(options: Options): Workbook {
  return buildSuspiciousWorkbook({ generatedAt: GENERATED, ...options })
}

/** A cell's value, whatever kind of cell it is. */
function valueOf(cell: unknown): unknown {
  if (cell && typeof cell === 'object' && 'value' in cell) {
    return (cell as { value?: unknown }).value
  }
  return undefined
}

/** Every non-empty cell of a sheet, flattened — for "does this text appear". */
function flat(sheet: Sheet): string[] {
  return sheet.data
    .flat()
    .map((cell) => {
      const value = valueOf(cell)
      return value === undefined || value === null ? '' : String(value)
    })
    .filter(Boolean)
}

function sheetNamed(workbook: Workbook, name: string): Sheet {
  const sheet = workbook.sheets.find((item) => item.sheet === name)
  if (!sheet) throw new Error(`no sheet named ${name}`)
  return sheet
}

/**
 * The figure beside a label on the summary sheet.
 *
 * The LAST row carrying the label, because "Shubhali savdolar" is both the
 * file's title and a metric's label — the title is row one.
 */
function metric(sheet: Sheet, label: string): unknown {
  const rows = sheet.data.filter((row) => valueOf(row[0]) === label)
  const row = rows[rows.length - 1]
  return row ? valueOf(row[1]) : undefined
}

/** The table's header row and the index it sits at — the frozen count minus
 *  the header itself, exactly as the file builds it. */
function headerRow(sheet: Sheet): { index: number; headers: string[] } {
  const index = (sheet.stickyRowsCount ?? 1) - 1
  const row = sheet.data[index] ?? []
  return { index, headers: row.map((cell) => String(valueOf(cell) ?? '')) }
}

/** A single cell of a table sheet, by header name and row offset. */
function cellUnder(sheet: Sheet, header: string, offset: number): unknown {
  const { index, headers } = headerRow(sheet)
  const column = headers.indexOf(header)
  expect(column).toBeGreaterThanOrEqual(0)
  return (sheet.data[index + 1 + offset] ?? [])[column]
}

const SUMMARY = () => t('sales.exportSuspicious.sheetSummary')
const SALES = () => t('sales.export.sheetSales')
const AGENTS = () => t('sales.exportSuspicious.sheetAgents')
const CLIENTS = () => t('sales.exportSuspicious.sheetClients')
const TIMELINE = () => t('sales.exportSuspicious.sheetTimeline')

/** Three suspicious sales: two customers, two employees, one decided. */
function threeRows() {
  return [
    makeItem({ amount_usd: 340, broken_rules: ['R1'] }),
    makeItem({
      id: 'b',
      external_id: '88682',
      occurred_on: '2026-08-14',
      amount_usd: 160,
      broken_rules: ['R1', 'R3'],
      calls_total: 0,
      review: { status: 'justified', reason: 'walk_in', note: 'Kelib oldi', reviewed_by: 'Aziz', reviewed_at: '2026-08-15T05:00:00Z' },
    }),
    makeItem({
      id: 'c',
      external_id: '88683',
      partner_code: 'К02712',
      partner_name: 'Beta Servis',
      occurred_on: '2026-08-10',
      agent_id: null,
      agent_name: null,
      branch: 'Кукон метан булими',
      amount_usd: 500,
      broken_rules: ['R2'],
    }),
  ]
}

describe('the summary sheet', () => {
  it('counts the suspicious sales, the customers and the employees from the rows', () => {
    const summary = sheetNamed(build({ rows: threeRows(), summary: makeSummary() }), SUMMARY())

    expect(metric(summary, t('sales.exportSuspicious.count'))).toBe(3)
    // Two distinct customer codes across the three sales.
    expect(metric(summary, t('sales.exportSuspicious.clients'))).toBe(2)
    // ⚠️ ONE employee, not two: the third sale's branch is linked to nobody
    // and is reported as unlinked instead of inflating the head count.
    expect(metric(summary, t('sales.exportSuspicious.agents'))).toBe(1)
    expect(flat(summary).join(' | ')).toContain(
      t('sales.exportSuspicious.unlinked', { branches: 1, sales: 1 }),
    )
    // 340 + 160 + 500, and the document-currency amounts are never added.
    expect(metric(summary, t('sales.col.amountUsd'))).toBe(1000)
  })

  it('counts the decisions from the rows, not from the summary', () => {
    const summary = sheetNamed(build({ rows: threeRows(), summary: makeSummary() }), SUMMARY())

    // The fixture summary says 41/3/1 over the WHOLE selection; this sheet is
    // about the three suspicious rows and must say 2/1/0.
    expect(metric(summary, t('sales.review.new'))).toBe(2)
    expect(metric(summary, t('sales.review.justified'))).toBe(1)
    expect(metric(summary, t('sales.review.confirmed'))).toBe(0)
  })

  it('counts each broken rule separately, and says the figures do not add up', () => {
    const summary = sheetNamed(build({ rows: threeRows(), summary: makeSummary() }), SUMMARY())

    // Two rows carry R1, one of which also carries R3 — so 2 + 1 + 1 > 3.
    expect(metric(summary, 'R1')).toBe(2)
    expect(metric(summary, 'R2')).toBe(1)
    expect(metric(summary, 'R3')).toBe(1)
    expect(flat(summary).join(' | ')).toContain(t('sales.exportSuspicious.rulesNote'))
  })

  it('states R1 with the window it was computed against', () => {
    const rows = threeRows()
    const withWindow = sheetNamed(build({ rows, windowDays: 3 }), SUMMARY())
    expect(flat(withWindow)).toContain(t('sales.rule.R1window', { count: 3 }))

    // The window also travels on the summary response, so the caller need not
    // pass it twice.
    const fromSummary = sheetNamed(build({ rows, summary: makeSummary() }), SUMMARY())
    expect(flat(fromSummary)).toContain(t('sales.rule.R1window', { count: 3 }))

    // With no window known at all, the one-clause sentence is used rather than
    // a printed `{count}`.
    const without = sheetNamed(build({ rows }), SUMMARY())
    expect(flat(without)).toContain(t('sales.rule.R1'))
    expect(flat(without).join(' ')).not.toContain('{count}')
  })

  it('works out the share only when the whole selection is known', () => {
    const rows = threeRows()
    const withSummary = sheetNamed(build({ rows, summary: makeSummary() }), SUMMARY())
    // `pct` stores the Excel fraction: 3 of 451.
    expect(metric(withSummary, t('sales.exportSuspicious.share'))).toBeCloseTo(3 / 451, 6)
    expect(flat(withSummary)).toContain(t('sales.exportSuspicious.ofTotal', { count: 451 }))

    const alone = sheetNamed(build({ rows }), SUMMARY())
    expect(metric(alone, t('sales.exportSuspicious.share'))).toBeUndefined()
  })

  it('carries the warning that the list accuses nobody, and the period', () => {
    const summary = sheetNamed(
      build({
        rows: threeRows(),
        since: '2026-07-22',
        until: '2026-08-20',
        scope: 'Doimiy mijozlar',
      }),
      SUMMARY(),
    )
    const head = flat(summary).join(' | ')

    expect(head).toContain(t('sales.subtitle'))
    expect(head).toContain('22/07/2026')
    expect(head).toContain('20/08/2026')
    expect(head).toContain(t('sales.export.rows', { count: 3 }))
    expect(head).toContain('Doimiy mijozlar')
  })
})

describe('the sales sheet', () => {
  it('writes one row per sale under a frozen header, and totals them inside the table', () => {
    const rows = threeRows()
    const sales = sheetNamed(build({ rows }), SALES())
    const { index, headers } = headerRow(sales)

    expect(headers[0]).toBe(t('sales.col.date'))
    // The header block, the header row, three sales and the total row.
    expect(sales.data.length).toBe(index + 1 + rows.length + 1)
    expect(sales.stickyColumnsCount).toBe(1)

    const total = sales.data[sales.data.length - 1] ?? []
    expect(valueOf(total[0])).toBe(t('sales.export.totalRow'))
    // The row count sits beside the label; the dollar total under its column.
    expect(valueOf(total[1])).toBe(3)
    expect(valueOf(total[headers.indexOf(t('sales.col.amountUsd'))])).toBe(1000)
    // ⚠️ The document-currency column is deliberately EMPTY: som and dollars
    // do not add up to anything.
    expect(valueOf(total[headers.indexOf(t('sales.col.amount'))])).toBeUndefined()
  })

  it('writes the last call on the Tashkent wall clock', () => {
    const sales = sheetNamed(
      build({ rows: [makeItem({ last_call_at: '2026-08-03T09:14:00Z' })] }),
      SALES(),
    )
    const cell = cellUnder(sales, t('sales.col.lastCall'), 0)

    // 09:14 UTC is 14:14 in Tashkent, and the file must open on 14:14.
    expect((valueOf(cell) as Date).toISOString()).toBe('2026-08-03T14:14:00.000Z')
  })
})

describe('an absent figure is not a zero', () => {
  it('leaves the money cell empty when SAP sent none', () => {
    const sales = sheetNamed(build({ rows: [makeItem({ amount_usd: null })] }), SALES())

    expect(valueOf(cellUnder(sales, t('sales.col.amountUsd'), 0))).toBeUndefined()
    // The row still exists and is still styled — an empty cell, not a gap.
    expect(cellUnder(sales, t('sales.col.amountUsd'), 0)).toBeTypeOf('object')
  })

  it('leaves the customer count empty when no timeline was fetched', () => {
    const agents = sheetNamed(build({ rows: threeRows() }), AGENTS())

    // ⚠️ NOT A ZERO. "How many customers did this employee sell to" cannot be
    // answered from the suspicious rows, and a zero would be a lie.
    expect(valueOf(cellUnder(agents, t('sales.exportSuspicious.clientsCol'), 0))).toBeUndefined()
    // What IS known from the rows is written: the suspicious customers.
    expect(
      valueOf(cellUnder(agents, t('sales.exportSuspicious.suspiciousClients'), 0)),
    ).toBe(1)
  })

  it('leaves the sales column empty when the whole selection is unknown', () => {
    const agents = sheetNamed(build({ rows: threeRows() }), AGENTS())
    expect(valueOf(cellUnder(agents, t('sales.col.sales'), 0))).toBeUndefined()

    const counted = sheetNamed(build({ rows: threeRows(), summary: makeSummary() }), AGENTS())
    expect(valueOf(cellUnder(counted, t('sales.col.sales'), 0))).toBe(120)
  })
})

describe('a sale nobody has decided on', () => {
  it('is written as undecided rather than left blank, and counted as new', () => {
    const workbook = build({ rows: [makeItem({ review: null })] })
    const sales = sheetNamed(workbook, SALES())

    expect(valueOf(cellUnder(sales, t('sales.col.decision'), 0))).toBe(t('sales.review.new'))
    // Its reason and note stay EMPTY — there is no decision to give a reason.
    expect(valueOf(cellUnder(sales, t('sales.col.decisionReason'), 0))).toBeUndefined()
    expect(valueOf(cellUnder(sales, t('sales.col.note'), 0))).toBeUndefined()

    expect(metric(sheetNamed(workbook, SUMMARY()), t('sales.review.new'))).toBe(1)
  })
})

describe('nothing to review', () => {
  it('says so on every table sheet instead of showing a bare heading', () => {
    const workbook = build({ rows: [], since: '2026-07-22', until: '2026-08-20' })

    for (const name of [SALES(), AGENTS(), CLIENTS()]) {
      const sheet = sheetNamed(workbook, name)
      expect(flat(sheet)).toContain(t('sales.exportSuspicious.none'))
      // No total row under no rows — "Jami 0" reads as a measured nothing.
      expect(flat(sheet)).not.toContain(t('sales.export.totalRow'))
    }

    // The summary still states the zero, which IS the answer here.
    expect(metric(sheetNamed(workbook, SUMMARY()), t('sales.exportSuspicious.count'))).toBe(0)
  })

  it('keeps a clean sale out of a file headed "suspicious"', () => {
    const workbook = build({ rows: [makeItem({ verdict: 'ok' }), makeItem({ verdict: 'not_checkable' })] })

    expect(metric(sheetNamed(workbook, SUMMARY()), t('sales.exportSuspicious.count'))).toBe(0)
    expect(flat(sheetNamed(workbook, SALES()))).toContain(t('sales.exportSuspicious.none'))
  })
})

describe('the customer sheet', () => {
  it('groups by code and names the sellers as the screen does', () => {
    const clients = sheetNamed(build({ rows: threeRows() }), CLIENTS())

    // Two sales on К02711, one on К02712 — the busier customer comes first.
    expect(valueOf(cellUnder(clients, t('sales.col.code'), 0))).toBe('К02711')
    expect(valueOf(cellUnder(clients, t('sales.verdict.suspicious'), 0))).toBe(2)
    // `sellerName` falls back to SAP's own wording for an unlinked sale.
    expect(valueOf(cellUnder(clients, t('sales.exportSuspicious.sellers'), 1))).toBe(
      'Кукон метан булими',
    )
    // The first and last sale of that customer, from the rows themselves.
    expect((valueOf(cellUnder(clients, t('sales.exportSuspicious.firstSale'), 0)) as Date)
      .toISOString()).toBe('2026-08-12T00:00:00.000Z')
    expect((valueOf(cellUnder(clients, t('sales.exportSuspicious.lastSale'), 0)) as Date)
      .toISOString()).toBe('2026-08-14T00:00:00.000Z')
  })
})

describe('the timeline sheet', () => {
  it('is left out entirely when no chain was fetched', () => {
    const workbook = build({ rows: threeRows() })

    expect(workbook.sheets.map((sheet) => sheet.sheet)).toEqual([
      SUMMARY(),
      SALES(),
      AGENTS(),
      CLIENTS(),
      t('sales.exportSuspicious.sheetGlossary'),
    ])
    // ⚠️ And its columns are not explained in the glossary of a sheet that is
    // not in the file.
    expect(flat(sheetNamed(workbook, t('sales.exportSuspicious.sheetGlossary')))).not.toContain(
      t('sales.exportSuspicious.timelineNote'),
    )
  })

  it('keeps the server’s order — the call before the sale on the same day', () => {
    const workbook = build({ rows: threeRows(), timeline: makeTimeline() })
    const timeline = sheetNamed(workbook, TIMELINE())
    const { index, headers } = headerRow(timeline)
    const event = headers.indexOf(t('sales.exportSuspicious.event'))
    const day = headers.indexOf(t('sales.col.date'))

    // The heading row of the customer, then its three events untouched.
    const rows = timeline.data.slice(index + 2)
    expect(
      rows.map((row) => [
        valueOf(row[event]),
        (valueOf(row[day]) as Date | undefined)?.toISOString().slice(0, 10),
      ]),
    ).toEqual([
      [t('sales.exportSuspicious.eventSale'), '2026-07-28'],
      // ⚠️ THE CALL COMES FIRST ON 12.08. A sale's `at` is 00:00 of its day, so
      // re-sorting by `at` here would put the sale ahead of it and quietly
      // contradict the rule the verdict was computed with.
      [t('sales.exportSuspicious.eventCall'), '2026-08-12'],
      [t('sales.exportSuspicious.eventSale'), '2026-08-12'],
    ])
  })

  it('writes a call’s clock but never a sale’s', () => {
    const timeline = sheetNamed(build({ rows: threeRows(), timeline: makeTimeline() }), TIMELINE())
    const { index, headers } = headerRow(timeline)
    const time = headers.indexOf(t('sales.exportSuspicious.time'))
    const rows = timeline.data.slice(index + 2)

    // 04:14 UTC is 09:14 in Tashkent.
    expect((valueOf((rows[1] ?? [])[time]) as Date).toISOString()).toBe('2026-08-12T09:14:00.000Z')
    // ⚠️ SAP gives a sale no clock, and 00:00 would be the lie "at midnight".
    expect(valueOf((rows[0] ?? [])[time])).toBeUndefined()
    expect(valueOf((rows[2] ?? [])[time])).toBeUndefined()
  })

  it('says when the list was cut, and pushes the frozen rows down with it', () => {
    const whole = sheetNamed(build({ rows: threeRows(), timeline: makeTimeline() }), TIMELINE())
    expect(flat(whole).join(' ')).not.toContain(t('sales.exportSuspicious.truncated', { count: 1 }))
    expect(whole.stickyRowsCount).toBe(5)
    expect(whole.stickyColumnsCount).toBe(3)

    const cut = sheetNamed(
      build({ rows: threeRows(), timeline: makeTimeline({ truncated: true }) }),
      TIMELINE(),
    )
    // A customer missing from the sheet is NOT a customer with nothing
    // against them, and the sheet has to say so itself.
    expect(flat(cut).join(' ')).toContain(t('sales.exportSuspicious.truncated', { count: 1 }))
    // The warning and its blank line push the table down by two rows, and the
    // frozen count comes from the sheet rather than from a hand-written number.
    expect(cut.stickyRowsCount).toBe(7)
  })

  it('will not take the customer count from a suspicious-only chain', () => {
    // Every customer in the fixture chain carries a suspicion, so the chain
    // cannot answer "how many customers in total" — the column stays empty.
    const narrow = sheetNamed(build({ rows: threeRows(), timeline: makeTimeline() }), AGENTS())
    expect(valueOf(cellUnder(narrow, t('sales.exportSuspicious.clientsCol'), 0))).toBeUndefined()

    // With a clean customer in the chain it IS the whole picture, and the
    // figure is written.
    const full = makeTimeline()
    const [first] = full.clients ?? []
    if (!first) throw new Error('the fixture chain is empty')
    const timeline = makeTimeline({
      clients: [
        first,
        {
          ...first,
          partner_code: 'К02712',
          partner_name: 'Beta Servis',
          suspicious_count: 0,
          sales_count: 1,
        },
      ],
    })
    const wide = sheetNamed(build({ rows: threeRows(), timeline }), AGENTS())
    expect(valueOf(cellUnder(wide, t('sales.exportSuspicious.clientsCol'), 0))).toBe(2)
  })
})

describe('the file name', () => {
  it('carries the period, so a folder of these files can be told apart', () => {
    expect(fileName(threeRows(), '2026-07-22', '2026-08-20', GENERATED)).toBe(
      `${t('sales.exportSuspicious.file')}-2026-07-22_2026-08-20.xlsx`,
    )
  })

  it('takes the period from the rows when the date filter is empty', () => {
    expect(fileName(threeRows(), undefined, undefined, GENERATED)).toBe(
      `${t('sales.exportSuspicious.file')}-2026-08-10_2026-08-14.xlsx`,
    )
  })

  it('falls back to the day it was downloaded when nothing was selected', () => {
    expect(fileName([], undefined, undefined, GENERATED)).toBe(
      `${t('sales.exportSuspicious.file')}-2026-08-21.xlsx`,
    )
  })
})
