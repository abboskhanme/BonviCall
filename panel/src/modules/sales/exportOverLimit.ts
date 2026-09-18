/**
 * "Walk-in customers → sales over the ticket limit" — the Excel file.
 *
 * Ported from `../BonviZvonki/services/web/src/modules/sales/exportOverLimit.ts`,
 * comments translated (CONVENTIONS.md §14). Its opening argument is still true
 * here and is kept:
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * WHY A REPORT OF ITS OWN, NOT ONE MORE SHEET IN `export.ts`. The general
 * export is a wide evidence table: last call, broken rules, previous sale,
 * conversations in between. For a walk-in customer HALF of those columns are
 * meaningless — one code, a hundred people, so "was THIS customer spoken to?"
 * is not even a question, and the rules (R1-R3) do not apply at all. Handing
 * that file to this section would show a manager whole empty columns, and an
 * empty column is read as data lost.
 *
 * The question here is ONE, and it is a different one: which tickets went over
 * the limit, and by how much. So the file is built around it — the amount, the
 * part above the limit, and the employee.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ── THE SHEETS ────────────────────────────────────────────────
 *
 *   1. "Xulosa"             the limit, how many sales, how much money.
 *   2. "Savdolar"           the table, the largest sale on top.
 *   3. "Xodimlar bo'yicha"  whose tickets went over the limit.
 *   4. "Izohlar"            the columns, the limit, the decisions.
 *
 * The library is imported DYNAMICALLY — it is only needed when the button is
 * pressed. A static import would ship it to every reader of the page, including
 * everyone who never exports anything.
 *
 * ── TESTING ───────────────────────────────────────────────────
 * `buildOverLimitWorkbook` is PURE: rows in, sheet descriptors out. It touches
 * no DOM and does not load the library, so the arithmetic and the layout are
 * testable in Node. `exportOverLimitSales` is the thin shell that writes the
 * file. `modules/activity/export.ts` is this repo's precedent for the split.
 *
 * ── WHAT THE PORT CHANGED ─────────────────────────────────────
 *   · No `TFunction` is passed in: there is one language and one catalogue
 *     (`@/shared/i18n`), and a key is a compile-checked literal.
 *   · Instants are written on the Asia/Tashkent wall clock, because the house
 *     kit writes them that way and the screen reads that way (SPEC §5.3).
 *   · The filter-and-sort moved OUT of the entry point and INTO the builder, so
 *     the test can see it (it is a correctness guard, see below).
 */
import type { CellObject, Row, Sheet, SheetData } from 'write-excel-file/browser'

import { t } from '@/shared/i18n'
import { formatCount, formatDateTime, formatPhone } from '@/shared/lib/format'
import {
  BAD,
  HEADER,
  INK,
  META,
  MUTED,
  NAVY,
  RULE,
  SECTION,
  TITLE,
  TOTAL,
  WARN,
  type CellStyle,
  date,
  datetime,
  glossaryRows,
  money,
  note,
  num,
  pct,
  span,
  text,
} from '@/shared/lib/xlsx'

import { REVIEW_LABEL, type ComplianceItem, type ComplianceSummary } from './api'
import { periodOf, periodStamp } from './export'
import { formatSaleDate } from './saleDate'
import { sellerName, sellerUnlinked } from './seller'

/** One row of a sheet. Re-exported so a test can name it without importing the
 *  library, which is the one thing this module is careful not to load early. */
export type SheetRow = Row

/* ── The arithmetic ───────────────────────────────────────── */

/**
 * The part of a sale that is ABOVE the limit.
 *
 * Never negative: the caller only hands over `over_limit` rows, but if the
 * limit was raised in the settings after the list on screen was fetched, the
 * subtraction would go negative and the cell would read "−120 $ over the
 * limit", which is nonsense.
 *
 * `null` in, `null` out — SAP leaves the dollar figure empty often enough, and
 * an empty cell is not the same statement as a zero.
 */
export function excessOf(row: ComplianceItem, limit: number): number | null {
  if (row.amount_usd == null) return null
  return Math.max(0, row.amount_usd - limit)
}

/**
 * The colour of the part above the limit.
 *
 * Two levels, because they call for two different actions: a ticket a little
 * over the limit is an ordinary large purchase, one at twice the limit is
 * nearly always a REGULAR customer written under the wrong code. Colouring
 * every excess the same red would erase that difference, and a list that is red
 * throughout has stopped signalling anything.
 */
function excessColor(row: ComplianceItem, limit: number): string | undefined {
  const over = excessOf(row, limit)
  if (over == null || over <= 0) return undefined
  return over >= limit ? BAD : WARN
}

/** One line of the employee cut — the same shape wherever it is built. */
interface AgentStat {
  name: string | null
  count: number
  amount: number
  /** ⚠️ Only ever computed from `rows` — see `agentStats` below. */
  largest: number | null
}

/**
 * The employee cut of `rows`.
 *
 * The key is `agent_id`; sales with no employee (a branch deliberately linked
 * to nobody) collect into ONE line under the empty key.
 *
 * ⚠️ `sellerName()` is deliberately NOT used for the label here, although it is
 * used in the sales table. It answers "who sold this ONE sale" and falls back
 * to SAP's own branch name; in a bucket that merges several unlinked branches
 * the first branch's name would then stand for all of them. The server's own
 * per-employee cut merges them the same way, and this sheet has to reconcile
 * with it, so the merged line stays nameless and is labelled "Xodim
 * biriktirilmagan".
 */
function statsFromRows(rows: ComplianceItem[]): Map<string, AgentStat> {
  const map = new Map<string, AgentStat>()
  for (const row of rows) {
    const key = row.agent_id ?? ''
    const stat = map.get(key) ?? {
      name: row.agent_name ?? null,
      count: 0,
      amount: 0,
      largest: null,
    }
    const amount = row.amount_usd ?? 0
    stat.count += 1
    stat.amount += amount
    stat.largest = stat.largest == null ? amount : Math.max(stat.largest, amount)
    map.set(key, stat)
  }
  return map
}

/**
 * The employee cut.
 *
 * ⚠️ TWO SOURCES, ON PURPOSE. The count and the amount come from
 * `summary.agents` (the server computes those over the SCOPE, and the card on
 * screen shows exactly that number; the file must not contradict the screen).
 * The largest sale comes from `rows` alone — `AgentBreakdownOut` has no such
 * field and it cannot be approximated.
 *
 * The two need not agree: the summary is by scope, the list is by the review
 * filter on screen (default — "undecided"). So the difference is NOT swallowed,
 * it is written out at the foot of the sheet.
 */
function agentStats(
  rows: ComplianceItem[],
  summary: ComplianceSummary | undefined,
): AgentStat[] {
  const fromRows = statsFromRows(rows)
  const byAmount = (a: AgentStat, b: AgentStat) => b.amount - a.amount

  if (!summary?.agents?.length) {
    return [...fromRows.values()].sort(byAmount)
  }

  return summary.agents
    /* An employee with no sale over the limit has no place on this sheet: they
       would only add lines full of zeroes and make the list longer. */
    .filter((agent) => agent.over_limit > 0)
    .map((agent) => ({
      name: agent.agent_name ?? null,
      count: agent.over_limit,
      amount: agent.over_limit_amount,
      largest: fromRows.get(agent.agent_id ?? '')?.largest ?? null,
    }))
    .sort(byAmount)
}

/** An average without a division by zero. `null` leaves the cell empty. */
function average(amount: number, count: number): number | null {
  return count ? amount / count : null
}

/* ── Columns ──────────────────────────────────────────────── */

interface Column {
  header: string
  width: number
  /** Excel right-aligns numbers, and the heading has to sit over the figures —
   *  otherwise the table looks crooked. */
  align?: 'left' | 'right' | 'center'
  cell: (row: ComplianceItem, base: CellStyle) => CellObject
  /** The cell in the "Jami" row. Defined WITH the column: in a separate array
   *  a new column would silently shift the total row and put figures under the
   *  wrong heading. */
  total?: (rows: ComplianceItem[], base: CellStyle) => CellObject
}

function columns(limit: number): Column[] {
  /* ⚠️ The picker admits `undefined` as well as `null`: on the GENERATED type
     the money fields are OPTIONAL (`amount_usd?: number | null`), where the
     source's hand-written interface made them merely nullable. Both mean "SAP
     had no figure", and both add nothing to a total. */
  const sum = (
    rows: ComplianceItem[],
    pick: (row: ComplianceItem) => number | null | undefined,
  ) => rows.reduce((acc, row) => acc + (pick(row) ?? 0), 0)

  return [
    {
      /* ⚠️ THE DATE ONLY. SAP gives a sale no clock (`occurred_on` is a date),
         so no time is shown here: an empty `00:00` would read as a real one.
         The house kit passes a bare `YYYY-MM-DD` through untouched, which is
         the defect `saleDate.ts` documents at length. */
      header: t('sales.col.date'),
      width: 12,
      align: 'center',
      cell: (row, base) => date(row.occurred_on, { align: 'center', ...base }),
    },
    {
      /* SAP's `Номер операции` — the number a manager finds the row in SAP by.
         It is what makes the whole file checkable. */
      header: t('sales.col.operation'),
      width: 14,
      cell: (row, base) => text(row.external_id, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.document'),
      width: 13,
      cell: (row, base) => text(row.doc_number, { textColor: MUTED, ...base }),
    },
    {
      /* The shared code. Repetition in this column is NORMAL and is exactly
         why it is here: dozens of sales under one code are the reason this
         section exists at all. */
      header: t('sales.col.code'),
      width: 12,
      cell: (row, base) => text(row.partner_code, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.client'),
      width: 30,
      cell: (row, base) => text(row.partner_name, base),
    },
    {
      /* Rendered with the panel's ONE phone formatter, not raw as the source
         had it: the file has to read like the screen, and this product has a
         single rendering of a number (CONVENTIONS.md §7). A number the
         formatter cannot parse falls through as SAP wrote it. */
      header: t('sales.col.phone'),
      width: 16,
      cell: (row, base) => text(formatPhone(row.phone) ?? row.phone, base),
    },
    {
      header: t('sales.col.branch'),
      width: 22,
      cell: (row, base) => text(row.branch, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.direction'),
      width: 12,
      cell: (row, base) => text(row.direction, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.agent'),
      width: 20,
      /**
       * ⚠️ `sellerName`, not `agent_name`, and NEVER an empty cell.
       *
       * SAP's `Подразделение` IS the employee (`seller.ts`): people are written
       * there under the territory they work, and sometimes under their own
       * name. So an unlinked sale prints SAP's own word in the warning tone
       * rather than nothing — and yes, that repeats the "SAP filiali" column
       * beside it. The repetition is the lesser evil: the SAP column is what
       * the manager searches SAP by, and a blank employee cell would read as a
       * fault when some branches are unlinked ON PURPOSE.
       */
      cell: (row, base) => {
        const name = sellerName(row)
        if (!name) return text(t('sales.noAgent'), { textColor: MUTED, ...base })
        return text(name, { textColor: sellerUnlinked(row) ? WARN : undefined, ...base })
      },
    },
    {
      /* The document's own currency — secondary: comparison is only meaningful
         in dollars, and this column is for matching against SAP. */
      header: t('sales.col.amount'),
      width: 16,
      align: 'right',
      cell: (row, base) => money(row.amount, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.currency'),
      width: 9,
      align: 'center',
      cell: (row, base) => text(row.currency, { align: 'center', textColor: MUTED, ...base }),
    },
    {
      /* THE AXIS of the report: both the limit and the sort order live here. */
      header: t('sales.col.amountUsd'),
      width: 14,
      align: 'right',
      cell: (row, base) => money(row.amount_usd, { fontWeight: 'bold', ...base }),
      total: (rows, base) => money(sum(rows, (row) => row.amount_usd), base),
    },
    {
      header: t('sales.exportOverLimit.colExcess'),
      width: 17,
      align: 'right',
      cell: (row, base) =>
        money(excessOf(row, limit), { textColor: excessColor(row, limit), ...base }),
      total: (rows, base) =>
        money(sum(rows, (row) => excessOf(row, limit)), { textColor: BAD, ...base }),
    },
    {
      /* DATE AND TIME. A call's time is EXACT (a sale's is not) and it is the
         only exact time in this file — cutting it would throw away evidence. */
      header: t('sales.col.lastCall'),
      width: 19,
      cell: (row, base) =>
        row.last_call_at
          ? datetime(row.last_call_at, base)
          : /* ⚠️ NOT RED. For a regular customer "no call at all" is a problem;
               here it is the ORDINARY case — somebody walked in and left, and
               we do not have their number. Red would be a false signal. */
            text(t('sales.noCallEver'), { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.lastCallAgent'),
      width: 20,
      cell: (row, base) => text(row.last_call_agent, base),
    },
    {
      header: t('sales.col.daysBefore'),
      width: 14,
      align: 'center',
      cell: (row, base) => num(row.days_before, { align: 'center', textColor: MUTED, ...base }),
    },
    {
      /* ⚠️ The label comes from `REVIEW_LABEL`, not from
         `t('sales.review.' + status)`: a catalogue key is a literal union here,
         so a status the server adds tomorrow is a compile error rather than a
         dotted identifier printed in a manager's spreadsheet. */
      header: t('sales.col.decision'),
      width: 20,
      cell: (row, base) =>
        row.review
          ? text(t(REVIEW_LABEL[row.review.status]), {
              textColor: row.review.status === 'justified' ? MUTED : BAD,
              fontWeight: 'bold',
              ...base,
            })
          : text(t(REVIEW_LABEL.new), { textColor: MUTED, ...base }),
    },
  ]
}

/* ── Sheet 1: the summary ─────────────────────────────────── */

/** How many columns the summary sheet has; notes span all of them. */
const SUMMARY_SPAN = 5
/** Their combined width in characters, for the note-height arithmetic. A
 *  little under the sum of `SUMMARY_WIDTHS`: a word that wraps whole leaves the
 *  line short. */
const SUMMARY_LINE = 112
const SUMMARY_WIDTHS = [34, 16, 26, 26, 24]

export interface Meta {
  period: string
  scope: string
  generated: string
}

/**
 * The summary sheet.
 *
 * ⚠️ EVERY FIGURE IS COMPUTED FROM `rows`, NOT FROM `summary`, and that is
 * deliberate: a number on this sheet has to come out EXACTLY right when a
 * manager adds up the column on sheet 2 by hand. They really do that, and two
 * numbers from two sources would destroy trust in the file in one sitting.
 * `summary` is used for context only: "out of how many walk-in sales".
 *
 * Cells are not merged into "cards": a merged cell breaks both copying and
 * sorting in Excel. Label on the left, figure beside it, note to the right.
 */
export function summarySheet(
  rows: ComplianceItem[],
  summary: ComplianceSummary | undefined,
  limit: number,
  meta: Meta,
): { data: SheetData; widths: number[] } {
  const amount = rows.reduce((acc, row) => acc + (row.amount_usd ?? 0), 0)
  const excess = rows.reduce((acc, row) => acc + (excessOf(row, limit) ?? 0), 0)
  const largest = rows.reduce<number | null>(
    (acc, row) =>
      row.amount_usd == null ? acc : acc == null ? row.amount_usd : Math.max(acc, row.amount_usd),
    null,
  )
  const agents = statsFromRows(rows).size

  const data: SheetData = [
    span(text(t('sales.exportOverLimit.title'), TITLE), SUMMARY_SPAN),
    span(text(meta.period, META), SUMMARY_SPAN),
    span(text(meta.scope, META), SUMMARY_SPAN),
    span(text(meta.generated, META), SUMMARY_SPAN),
    [],
    span(text(t('sales.exportOverLimit.metrics'), SECTION), SUMMARY_SPAN),
  ]

  /** One figure: label · number · note. */
  const metric = (label: string, value: CellObject, hint?: string): SheetRow => [
    text(label, { fontSize: 11, textColor: INK }),
    { ...value, fontWeight: 'bold', fontSize: 14 },
    ...(hint ? span(text(hint, { fontSize: 10, textColor: MUTED }), SUMMARY_SPAN - 2) : []),
  ]

  data.push(
    /* ⚠️ THE LIMIT IS PRINTED IN THE FILE, as a figure of its own. The setting
       can be changed tomorrow and nothing recomputes an old file, so the file
       has to state the basis it was built on. It is said twice more: in the
       note below, and in the glossary. */
    metric(
      t('sales.exportOverLimit.limit'),
      money(limit, { textColor: INK }),
      t('sales.exportOverLimit.limitSource'),
    ),
    metric(
      t('sales.exportOverLimit.count'),
      num(rows.length, { textColor: rows.length ? WARN : INK }),
      /* The denominator is the context: 6 out of 843 and 200 out of 843 are
         entirely different messages, though both show the same "over the
         limit" count. */
      summary ? t('sales.exportOverLimit.countOf', { total: summary.total }) : undefined,
    ),
    metric(t('sales.exportOverLimit.amount'), money(amount, { textColor: NAVY })),
    metric(
      t('sales.exportOverLimit.average'),
      money(average(amount, rows.length), { textColor: NAVY }),
    ),
    metric(
      t('sales.exportOverLimit.largest'),
      /* The biggest ticket, at twice the limit or more, is nearly always a
         regular customer written under the wrong code — the case worth
         checking. */
      money(largest, { textColor: largest != null && largest >= limit * 2 ? BAD : NAVY }),
    ),
    metric(t('sales.exportOverLimit.agents'), num(agents, { textColor: INK })),
    metric(
      t('sales.exportOverLimit.excessTotal'),
      money(excess, { textColor: excess > 0 ? BAD : INK }),
      t('sales.exportOverLimit.excessHint'),
    ),
  )

  data.push(
    [],
    note(
      t('sales.exportOverLimit.limitNote'),
      { fontSize: 10, textColor: MUTED },
      SUMMARY_SPAN,
      SUMMARY_LINE,
    ),
    note(
      t('sales.exportOverLimit.walkInNote'),
      { fontSize: 10, textColor: MUTED },
      SUMMARY_SPAN,
      SUMMARY_LINE,
    ),
  )

  return { data, widths: SUMMARY_WIDTHS }
}

/* ── Sheet 2: the sales ───────────────────────────────────── */

/** The total row's label, shared by sheets 2 and 3 so they cannot drift. */
const TOTAL_LABEL = 'sales.export.totalRow' as const

/**
 * The main table — one row per sale.
 *
 * ⚠️ SORTED BY AMOUNT, DESCENDING, not in the order on screen (the builder does
 * the sorting, so every sheet sees the same order). A manager reads this file
 * "largest money first", and in a date-sorted list the most expensive ticket
 * would sit somewhere in the middle. The date column is still there — re-sorting
 * in Excel is one click.
 */
export function salesSheet(
  rows: ComplianceItem[],
  limit: number,
  meta: Meta,
): { data: SheetData; widths: number[] } {
  const cols = columns(limit)
  const width = cols.length

  const data: SheetData = [
    span(
      text(t('sales.exportOverLimit.salesTitle'), {
        fontWeight: 'bold',
        fontSize: 12,
        textColor: INK,
      }),
      width,
    ),
    span(text(`${meta.period} · ${meta.scope}`, META), width),
    span(text(meta.generated, META), width),
    [],
    cols.map((column) => text(column.header, { ...HEADER, align: column.align ?? 'left' })),
  ]

  for (const row of rows) {
    data.push(cols.map((column) => column.cell(row, RULE)))
  }

  /* "Jami" sits INSIDE the table, as its last row. On a sheet of its own it
     would mean switching sheets to compare against it. */
  if (rows.length > 1) {
    data.push(
      cols.map((column, index) =>
        index === 0
          ? text(t(TOTAL_LABEL), TOTAL)
          : column.total
            ? column.total(rows, TOTAL)
            : { ...TOTAL },
      ),
    )
  }

  return { data, widths: cols.map((column) => column.width) }
}

/* ── Sheet 3: the employee cut ────────────────────────────── */

/**
 * "Whose tickets went over the limit".
 *
 * This sheet is NOT AN ACCUSATION, which is why it has no "violation" column:
 * with a walk-in buyer a large ticket may be the employee's mistake or an
 * ordinary big purchase. The sheet only shows where they collect; the
 * conclusion is the manager's.
 */
export function agentsSheet(
  stats: AgentStat[],
  rowCount: number,
  meta: Meta,
): { data: SheetData; widths: number[] } {
  const headers: [string, number, 'left' | 'right'][] = [
    /* ⚠️ The source used `table.agent`, which this catalogue does not have.
       `sales.col.agent` is the same word ("Xodim") and belongs to this module. */
    [t('sales.col.agent'), 30, 'left'],
    [t('sales.col.sales'), 14, 'right'],
    [t('sales.exportOverLimit.colAmount'), 18, 'right'],
    [t('sales.exportOverLimit.colAverage'), 18, 'right'],
    [t('sales.exportOverLimit.colLargest'), 18, 'right'],
    [t('sales.exportOverLimit.colShare'), 12, 'right'],
  ]

  const total = stats.reduce((acc, stat) => acc + stat.amount, 0)
  const count = stats.reduce((acc, stat) => acc + stat.count, 0)
  const largest = stats.reduce<number | null>(
    (acc, stat) =>
      stat.largest == null ? acc : acc == null ? stat.largest : Math.max(acc, stat.largest),
    null,
  )

  const data: SheetData = [
    span(
      text(t('sales.exportOverLimit.sheetAgents'), {
        fontWeight: 'bold',
        fontSize: 12,
        textColor: INK,
      }),
      headers.length,
    ),
    span(text(`${meta.period} · ${meta.scope}`, META), headers.length),
    [],
    headers.map(([header, , align]) => text(header, { ...HEADER, align })),
  ]

  for (const stat of stats) {
    data.push([
      stat.name ? text(stat.name, RULE) : text(t('sales.noAgent'), { textColor: MUTED, ...RULE }),
      num(stat.count, { align: 'center', ...RULE }),
      money(stat.amount, { fontWeight: 'bold', ...RULE }),
      money(average(stat.amount, stat.count), { textColor: MUTED, ...RULE }),
      money(stat.largest, RULE),
      /* The share is handed over on the 0-100 scale; `pct` converts it to the
         fraction Excel formats. */
      pct(total ? (stat.amount / total) * 100 : null, { textColor: MUTED, ...RULE }),
    ])
  }

  if (stats.length > 1) {
    data.push([
      text(t(TOTAL_LABEL), TOTAL),
      num(count, { align: 'center', ...TOTAL }),
      money(total, TOTAL),
      money(average(total, count), TOTAL),
      money(largest, TOTAL),
      pct(total ? 100 : null, TOTAL),
    ])
  }

  /* ⚠️ THE DIFFERENCE IS NOT SWALLOWED. The summary is computed over the SCOPE,
     while sheet 2's list follows the review filter on screen (default —
     "undecided"). Unstated, those two numbers make the file contradict itself,
     and the blame lands on the report. */
  if (count !== rowCount) {
    data.push(
      [],
      note(
        t('sales.exportOverLimit.mismatch', { summary: count, rows: rowCount }),
        { fontSize: 10, textColor: WARN },
        headers.length,
        104,
      ),
    )
  }

  return { data, widths: headers.map(([, width]) => width) }
}

/* ── Sheet 4: the glossary ────────────────────────────────── */

/**
 * The terms sheet.
 *
 * WHY IT EXISTS. The file travels by email and whoever opens it may never have
 * seen the screen — "the limit", "a walk-in customer" and "justified" cannot be
 * guessed from a column heading. The risk is higher in this report than in any
 * other: without the glossary it reads as "over the limit = guilty".
 */
export function glossarySheet(limit: number): { data: SheetData; widths: number[] } {
  const terms: [string, string][] = [
    [t('sales.col.date'), t('sales.exportOverLimit.tipDate')],
    [t('sales.col.operation'), t('sales.exportOverLimit.tipOperation')],
    [t('sales.col.document'), t('sales.exportOverLimit.tipDocument')],
    [t('sales.col.code'), t('sales.exportOverLimit.tipCode')],
    [t('sales.col.client'), t('sales.exportOverLimit.tipClient')],
    [t('sales.col.phone'), t('sales.exportOverLimit.tipPhone')],
    [t('sales.col.branch'), t('sales.exportOverLimit.tipBranch')],
    [t('sales.col.direction'), t('sales.exportOverLimit.tipDirection')],
    [t('sales.col.agent'), t('sales.exportOverLimit.tipAgent')],
    [t('sales.col.amount'), t('sales.exportOverLimit.tipAmount')],
    [t('sales.col.amountUsd'), t('sales.exportOverLimit.tipAmountUsd')],
    [t('sales.exportOverLimit.colExcess'), t('sales.exportOverLimit.tipExcess')],
    [t('sales.col.lastCall'), t('sales.exportOverLimit.tipLastCall')],
    [t('sales.col.lastCallAgent'), t('sales.exportOverLimit.tipLastCallAgent')],
    [t('sales.col.daysBefore'), t('sales.exportOverLimit.tipDaysBefore')],
    [t('sales.col.decision'), t('sales.exportOverLimit.tipDecision')],
    [t('sales.exportOverLimit.colShare'), t('sales.exportOverLimit.tipShare')],
    /* The terms come AFTER the columns: they explain the report rather than the
       table, and that is the order in which it is read.

       ⚠️ The limit is interpolated with `formatCount`, NOT with `formatUsd`:
       the catalogue sentence already carries its own "$" ("chegara: {limit} $"),
       and `formatUsd` would print it twice. Every other money figure in this
       file is a NUMBER cell, which is why the module's own money formatter
       appears exactly here and nowhere else. */
    [
      t('sales.exportOverLimit.termLimit'),
      t('sales.exportOverLimit.defLimit', { limit: formatCount(Math.round(limit)) }),
    ],
    [t('sales.kind.walk_in'), t('sales.exportOverLimit.defWalkIn')],
    [t('sales.col.decision'), t('sales.exportOverLimit.defReview')],
    [t('sales.exportOverLimit.termWarning'), t('sales.exportOverLimit.defWarning')],
  ]

  const data: SheetData = [
    span(
      text(t('sales.exportOverLimit.sheetGlossary'), {
        fontWeight: 'bold',
        fontSize: 12,
        textColor: INK,
      }),
      2,
    ),
    [],
    [
      text(t('sales.exportOverLimit.term'), { ...HEADER, height: 24, wrap: false }),
      text(t('sales.exportOverLimit.definition'), { ...HEADER, height: 24, wrap: false }),
    ],
    ...glossaryRows(terms),
  ]

  return { data, widths: [30, 100] }
}

/* ── The workbook ─────────────────────────────────────────── */

/** One sheet as the library wants it. No images, so nothing is omitted. */
export type OverLimitSheet = Sheet<Blob>

export interface OverLimitWorkbook {
  fileName: string
  sheets: OverLimitSheet[]
}

/**
 * ONE options type for the builder and the entry point, because the entry point
 * adds nothing to the inputs — two types here would only drift apart.
 */
export interface OverLimitExportOptions {
  /** The caller has already fetched these with `over_limit=true`. */
  rows: ComplianceItem[]
  summary?: ComplianceSummary
  /**
   * The window on screen — `YYYY-MM-DD`, with no clock (a sale has none).
   *
   * Both are optional because this panel's date filter may be empty, which
   * means "everything"; the period is then taken from the rows themselves
   * (`export.ts::periodOf`, one rule for all three sales files).
   */
  since?: string
  until?: string
  /** A short description of the filter on screen. */
  scope?: string
  /**
   * The ticket limit in force ($) — pass `summary?.walk_in_limit ?? 0`.
   *
   * ⚠️ Required rather than defaulted from `summary`, and the caller should not
   * reach this screen without it: at `0` every sale is "over the limit by its
   * whole amount" and the file says so in three places. A wrong basis stated
   * out loud is still better than a basis guessed here — which is why the value
   * is printed in the file at all.
   */
  limit: number
  /** Injected so the builder stays pure and its test is not time-dependent. */
  generatedAt?: Date
}

/**
 * The file name: `limitdan-oshgan-2026-07-22_2026-08-20.xlsx`.
 *
 * The window has to be in the name: these files pile up in a folder and nobody
 * can tell which month `limitdan-oshgan(3).xlsx` belongs to. The stamp is the
 * one every sales export uses, so the three name their periods alike.
 */
function fileName(
  rows: ComplianceItem[],
  since: string | undefined,
  until: string | undefined,
  generatedAt: Date,
): string {
  return `${t('sales.exportOverLimit.file')}-${periodStamp(rows, since, until, generatedAt)}.xlsx`
}

/**
 * Rows in, sheets out. **Pure** — no DOM, no library, no clock unless one is
 * handed in.
 */
export function buildOverLimitWorkbook({
  rows,
  summary,
  since,
  until,
  scope,
  limit,
  generatedAt = new Date(),
}: OverLimitExportOptions): OverLimitWorkbook {
  /* A guard, not distrust: the caller sends the filter, but on the day the
     `over_limit` filter is lost on the server this file would QUIETLY become
     the whole section while its title still read "over the limit". That is the
     worst kind of fault — the invisible one. The sort lives here too, so every
     sheet sees one order. `filter` copies first, so the caller's array is left
     as it was. */
  const listed = rows
    .filter((row) => row.over_limit)
    .sort((a, b) => (b.amount_usd ?? 0) - (a.amount_usd ?? 0))

  const period = periodOf(listed, since, until)
  const meta: Meta = {
    /* ⚠️ No `T00:00:00` is appended to the day, unlike the source: these are
       Asia/Tashkent calendar dates and the panel renders every instant in that
       zone, so appending a local midnight would print the previous day for any
       reader east of UTC+5 (`saleDate.ts`). With no dates on screen and no
       rows there is no period at all, and the line is left empty rather than
       printed as a pair of dashes. */
    period: period
      ? t('sales.export.period', {
          from: formatSaleDate(period.from),
          to: formatSaleDate(period.to),
        })
      : '',
    scope: [t('sales.kind.walk_in'), t('sales.export.rows', { count: listed.length }), scope]
      .filter((part): part is string => Boolean(part))
      .join(' · '),
    generated: t('sales.export.generated', { value: formatDateTime(generatedAt) }),
  }

  const overview = summarySheet(listed, summary, limit, meta)
  const sales = salesSheet(listed, limit, meta)
  const agents = agentsSheet(agentStats(listed, summary), listed.length, meta)
  const glossary = glossarySheet(limit)

  return {
    fileName: fileName(listed, since, until, generatedAt),
    sheets: [
      {
        data: overview.data,
        sheet: t('sales.exportOverLimit.sheetSummary'),
        columns: overview.widths.map((width) => ({ width })),
        /* ⚠️ THE GRID IS OFF ON EVERY SHEET. A grey grid makes everything in the
           file look like a raw table; with it off the only lines the eye sees
           are the ones drawn on purpose. `landscape` is for print: seventeen
           columns split across two pages in portrait. */
        showGridLines: false,
        orientation: 'landscape',
      },
      {
        data: sales.data,
        sheet: t('sales.export.sheetSales'),
        columns: sales.widths.map((width) => ({ width })),
        showGridLines: false,
        orientation: 'landscape',
        /* Title block (3 rows) + a blank row + the header row = 5. The first
           column is frozen as well: seventeen columns in, scrolled right,
           nobody could tell which sale a figure belongs to. */
        stickyRowsCount: 5,
        stickyColumnsCount: 1,
      },
      {
        data: agents.data,
        sheet: t('sales.exportOverLimit.sheetAgents'),
        columns: agents.widths.map((width) => ({ width })),
        showGridLines: false,
        stickyRowsCount: 4,
        stickyColumnsCount: 1,
      },
      {
        data: glossary.data,
        sheet: t('sales.exportOverLimit.sheetGlossary'),
        columns: glossary.widths.map((width) => ({ width })),
        showGridLines: false,
      },
    ],
  }
}

/** Build the workbook and write it. The only half that needs a browser. */
export async function exportOverLimitSales(options: OverLimitExportOptions): Promise<void> {
  const workbook = buildOverLimitWorkbook(options)
  const writeXlsxFile = (await import('write-excel-file/browser')).default
  await writeXlsxFile(workbook.sheets).toFile(workbook.fileName)
}
