/**
 * "Shubhali savdolar" — a SEPARATE Excel report, written for the manager.
 *
 * Ported from `../BonviZvonki/services/web/src/modules/sales/exportSuspicious.ts`,
 * comments translated (CONVENTIONS.md §14). Its opening argument is kept word
 * for word, because it is the reason this is not two more sheets on
 * `export.ts`:
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * WHY A FILE OF ITS OWN. `export.ts` writes the WHOLE selection — the clean
 * sales and the ones that could not be checked included. It is the ARCHIVE,
 * the "everything is in here" file. This one is a WORK QUEUE: it holds only
 * the sales somebody has to look at, so it is built the other way round —
 * the figures first, then the evidence table, then two cuts ("who has the
 * most" and "whose customer is this"). One file doing both would lose both:
 * the cuts are noise in an archive, and the clean rows are noise in a queue.
 *
 * ⚠️ THIS FILE ACCUSES NOBODY. "Suspicious" is the system's GUESS; the
 * decision belongs to a person (contract §1). That is why the screen's own
 * warning stands at the top of the first sheet: the file travels by email and
 * whoever opens it may never have seen the screen.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ── SHEETS ────────────────────────────────────────────────────
 *   1. "Xulosa"             the figures: how many, for how much, by decision
 *                           and by rule.
 *   2. "Savdolar"           the evidence table, one sale per row.
 *   3. "Xodimlar bo'yicha"  who has the most.
 *   4. "Mijozlar bo'yicha"  whose customer it is.
 *   5. "Xronologiya"        the SEQUENCE: conversations and sales on one axis
 *                           (only when a `timeline` is handed in).
 *   6. "Izohlar"            the columns, the rules and the ⚠️ about a sale's
 *                           clock.
 *
 * The style — colours, formats, cell builders — comes from `shared/lib/xlsx`
 * and is NOT redefined here: files from one company have to look like one
 * company wrote them, and the manager opens them side by side.
 *
 * ── TESTING ───────────────────────────────────────────────────
 * `buildSuspiciousWorkbook` is pure: rows in, sheet descriptors out. No DOM,
 * no library, and the clock is injected — so the arithmetic and the layout are
 * testable in Node. `exportSuspiciousSales` is the thin shell that loads the
 * library and writes the file; a static import would ship it to every reader
 * of the page (`activity/export.ts` has the same split for the same reason).
 */
import type { CellObject, Row, Sheet, SheetData } from 'write-excel-file/browser'

import { DIRECTION_LABEL, type CallDirection } from '@/modules/calls/labels'
import { t, type MessageKey } from '@/shared/i18n'
import { formatDateTime } from '@/shared/lib/format'
import {
  BAD,
  BAND,
  GOOD,
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

import {
  REASON_LABEL,
  REVIEW_LABEL,
  RULES,
  RULE_LABEL,
  VERDICT_LABEL,
  type AgentBreakdown,
  type ComplianceItem,
  type ComplianceSummary,
  type ComplianceTimeline,
  type Rule,
  type TimelineClient,
  type TimelineEvent,
} from './api'
import { periodOf, periodStamp } from './export'
import { formatSaleDate } from './saleDate'
import { sellerName } from './seller'

/** A sheet as this module builds it — the library's own type, minus images.
 *  The same shape `export.ts` uses, so the wiring pass sees one vocabulary. */
export type SuspiciousSheet = Omit<Sheet<Blob>, 'images'>

/* ── The header block ─────────────────────────────────────── */

interface Meta {
  period: string
  scope: string
  generated: string
}

/**
 * The top of every table sheet: its name, the period and filter, and when it
 * was downloaded.
 *
 * REPEATED ON EVERY SHEET, deliberately. A single sheet gets copied out of
 * Excel or printed on its own, and then "45 suspicious sales" says nothing
 * about which period it belongs to unless these lines travel with it.
 */
const HEAD_ROWS = 4

function head(title: string, meta: Meta, width: number): SheetData {
  return [
    span(text(title, TITLE), width),
    span(text(`${meta.period} · ${meta.scope}`, META), width),
    span(text(meta.generated, META), width),
    [],
  ]
}

/** An empty table looks like a fault when only its heading is there; one row
 *  states it as a RESULT instead. */
function emptyRow(width: number): Row {
  return span(text(t('sales.exportSuspicious.none'), { textColor: MUTED }), width)
}

/* ── The arithmetic ───────────────────────────────────────── */

/**
 * The dollar total.
 *
 * ⚠️ THE DOCUMENT-CURRENCY COLUMN IS NEVER SUMMED. One selection holds sales
 * in som and in dollars, and their sum is not a number that means anything.
 * `amount_usd` is the equivalent SAP itself supplied — comparison is only
 * meaningful in that one column.
 *
 * `null` counts as nothing: SAP leaves the amount cell empty on some rows and
 * one of them must not wipe out the whole total.
 */
function sumUsd(rows: ComplianceItem[]): number {
  return rows.reduce((acc, row) => acc + (row.amount_usd ?? 0), 0)
}

interface Decisions {
  new: number
  justified: number
  confirmed: number
}

/**
 * The decision cut — counted from `rows`, NOT taken from the summary.
 *
 * `ComplianceSummary` counts the whole selection (it deliberately accepts no
 * `verdict` filter — `api.ts` says why), while this sheet is about the
 * suspicious sales only. Mixing the two sources would make the file
 * contradict itself: 40 rows in the table, 57 decisions in the heading.
 */
function countDecisions(rows: ComplianceItem[]): Decisions {
  const counts: Decisions = { new: 0, justified: 0, confirmed: 0 }
  rows.forEach((row) => {
    if (!row.review) counts.new += 1
    else if (row.review.status === 'justified') counts.justified += 1
    else counts.confirmed += 1
  })
  return counts
}

/**
 * How often each rule was broken. One sale can break several, so these figures
 * do not add up to the total.
 *
 * ⚠️ The source guarded the increment with `if (rule in counts)`, because its
 * rule type was hand-written and could drift from the server's. Here `Rule` is
 * generated, so a fourth rule breaks the build at `RULES` and `RULE_LABEL`
 * instead of being silently dropped from a spreadsheet.
 */
function countRules(rows: ComplianceItem[]): Record<Rule, number> {
  const counts: Record<Rule, number> = { R1: 0, R2: 0, R3: 0 }
  rows.forEach((row) => {
    row.broken_rules.forEach((rule) => {
      counts[rule] += 1
    })
  })
  return counts
}

/**
 * A rule in words. R1 states the window it was computed with, so an old file
 * still says which threshold produced it after the setting is changed.
 *
 * With no window known the one-clause sentence is used instead of printing a
 * `{count}` placeholder at the reader.
 */
function ruleText(rule: Rule, windowDays: number | undefined): string {
  if (rule === 'R1' && windowDays != null) {
    return t('sales.rule.R1window', { count: windowDays })
  }
  return t(RULE_LABEL[rule])
}

/* ── The columns of sheet 2 ───────────────────────────────── */

/**
 * Filling the total row by MEANING rather than by index: if the column order
 * changes, the sum must not move to a different cell.
 */
type ColumnKey =
  | 'date'
  | 'operation'
  | 'document'
  | 'code'
  | 'client'
  | 'phone'
  | 'branch'
  | 'direction'
  | 'agent'
  | 'amount'
  | 'currency'
  | 'amountUsd'
  | 'rules'
  | 'lastCall'
  | 'lastCallAgent'
  | 'daysBefore'
  | 'previousSale'
  | 'callsBetween'
  | 'callsTotal'
  | 'decision'
  | 'decisionReason'
  | 'note'

interface Column {
  key: ColumnKey
  header: string
  /** What the column MEANS, for the glossary sheet.
   *
   *  ⚠️ CARRIED ON THE COLUMN, not in a second hand-written list as in the
   *  source. There the glossary repeated all 22 column names, and a column
   *  added here would simply have gone unexplained there. */
  tip: MessageKey
  width: number
  /** Excel right-aligns numbers; a heading left over its own column's edge
   *  makes the table look crooked. */
  align?: CellStyle['align']
  cell: (row: ComplianceItem, base: CellStyle) => CellObject
}

/**
 * EVERY evidence column — not one of them is dropped.
 *
 * The reason is the contract's §4: the manager re-counts the figure by hand.
 * When the last conversation was and with whom, how many days before the sale,
 * the previous sale, the conversations between the two and in the whole
 * history — without those the file cannot be checked against SAP, which is the
 * only thing it is for.
 */
function columns(): Column[] {
  return [
    {
      key: 'date',
      header: t('sales.col.date'),
      tip: 'sales.exportSuspicious.tip.date',
      width: 12,
      align: 'center',
      cell: (row, base) => date(row.occurred_on, { align: 'center', ...base }),
    },
    {
      /* SAP's `Номер операции` — the whole point of the file is here: this is
         the number the manager finds the row in SAP by. */
      key: 'operation',
      header: t('sales.col.operation'),
      tip: 'sales.exportSuspicious.tip.operation',
      width: 14,
      cell: (row, base) => text(row.external_id, { textColor: MUTED, ...base }),
    },
    {
      key: 'document',
      header: t('sales.col.document'),
      tip: 'sales.exportSuspicious.tip.document',
      width: 13,
      cell: (row, base) => text(row.doc_number, { textColor: MUTED, ...base }),
    },
    {
      key: 'code',
      header: t('sales.col.code'),
      tip: 'sales.exportSuspicious.tip.code',
      width: 12,
      cell: (row, base) => text(row.partner_code, { textColor: MUTED, ...base }),
    },
    {
      key: 'client',
      header: t('sales.col.client'),
      tip: 'sales.exportSuspicious.tip.client',
      width: 30,
      cell: (row, base) => text(row.partner_name, base),
    },
    {
      key: 'phone',
      header: t('sales.col.phone'),
      tip: 'sales.exportSuspicious.tip.phone',
      width: 16,
      /* As SAP wrote it, deliberately unformatted: this column is compared
         against SAP's own cell, and a prettified number no longer matches. */
      cell: (row, base) => text(row.phone, base),
    },
    {
      /* ⚠️ SAP's `Подразделение` IS THE EMPLOYEE, not a branch: people are
         written there under the name of their territory ("Нукус") and
         sometimes under their own. The "Xodim" column beside it is OUR
         employee card — both are needed, or the row cannot be found in SAP.
         (`seller.ts` shows one name on screen because a row has no space for
         two; a file being reconciled needs both.) */
      key: 'branch',
      header: t('sales.col.branch'),
      tip: 'sales.exportSuspicious.tip.branch',
      width: 18,
      cell: (row, base) => text(row.branch, base),
    },
    {
      key: 'direction',
      header: t('sales.col.direction'),
      tip: 'sales.exportSuspicious.tip.direction',
      width: 12,
      cell: (row, base) => text(row.direction, { textColor: MUTED, ...base }),
    },
    {
      key: 'agent',
      header: t('sales.col.agent'),
      tip: 'sales.exportSuspicious.tip.agent',
      width: 20,
      /* A sale with no employee is written out, never left blank: some names
         are DELIBERATELY unlinked, and an empty cell would read as a fault. */
      cell: (row, base) =>
        row.agent_name
          ? text(row.agent_name, base)
          : text(t('sales.noAgent'), { textColor: MUTED, ...base }),
    },
    {
      key: 'amount',
      header: t('sales.col.amount'),
      tip: 'sales.exportSuspicious.tip.amount',
      width: 18,
      align: 'right',
      cell: (row, base) => money(row.amount, base),
    },
    {
      key: 'currency',
      header: t('sales.col.currency'),
      tip: 'sales.exportSuspicious.tip.currency',
      width: 9,
      align: 'center',
      cell: (row, base) => text(row.currency, { align: 'center', ...base }),
    },
    {
      key: 'amountUsd',
      header: t('sales.col.amountUsd'),
      tip: 'sales.exportSuspicious.tip.amountUsd',
      width: 14,
      align: 'right',
      cell: (row, base) => money(row.amount_usd, { fontWeight: 'bold', ...base }),
    },
    {
      /* The CODE is in the column, its meaning on the "Izohlar" sheet: three
         full sentences do not fit one cell and would make the row three times
         taller than its neighbours. */
      key: 'rules',
      header: t('sales.col.rules'),
      tip: 'sales.exportSuspicious.tip.rules',
      width: 13,
      align: 'center',
      cell: (row, base) =>
        text(row.broken_rules.join(', '), {
          textColor: row.broken_rules.length ? WARN : undefined,
          align: 'center',
          ...base,
        }),
    },
    {
      key: 'lastCall',
      header: t('sales.col.lastCall'),
      tip: 'sales.exportSuspicious.tip.lastCall',
      width: 18,
      /* The instant is turned onto the Asia/Tashkent wall clock inside
         `datetime()` itself — both sales exports take it from there, and this
         is the column a manager reads to judge whether a conversation happened
         before the sale. */
      cell: (row, base) =>
        row.last_call_at
          ? datetime(row.last_call_at, base)
          : text(t('sales.noCallEver'), { textColor: BAD, ...base }),
    },
    {
      key: 'lastCallAgent',
      header: t('sales.col.lastCallAgent'),
      tip: 'sales.exportSuspicious.tip.lastCallAgent',
      width: 20,
      cell: (row, base) => text(row.last_call_agent, base),
    },
    {
      key: 'daysBefore',
      header: t('sales.col.daysBefore'),
      tip: 'sales.exportSuspicious.tip.daysBefore',
      width: 14,
      align: 'center',
      cell: (row, base) => num(row.days_before, { align: 'center', ...base }),
    },
    {
      key: 'previousSale',
      header: t('sales.col.previousSale'),
      tip: 'sales.exportSuspicious.tip.previousSale',
      width: 14,
      align: 'center',
      cell: (row, base) => date(row.previous_sale_on, { align: 'center', ...base }),
    },
    {
      key: 'callsBetween',
      header: t('sales.col.callsBetween'),
      tip: 'sales.exportSuspicious.tip.callsBetween',
      width: 14,
      align: 'center',
      /* Zero is R2's own evidence, so it has to stand out. A figure above zero
         is not coloured: it is not a problem. */
      cell: (row, base) =>
        num(row.calls_between, {
          align: 'center',
          textColor: row.calls_between === 0 ? WARN : undefined,
          ...base,
        }),
    },
    {
      key: 'callsTotal',
      header: t('sales.col.callsTotal'),
      tip: 'sales.exportSuspicious.tip.callsTotal',
      width: 13,
      align: 'center',
      cell: (row, base) =>
        num(row.calls_total, {
          align: 'center',
          textColor: row.calls_total === 0 ? BAD : undefined,
          ...base,
        }),
    },
    {
      key: 'decision',
      header: t('sales.col.decision'),
      tip: 'sales.exportSuspicious.tip.decision',
      width: 18,
      /* The colour shows the PERSON's decision, not the system's guess:
         "justified" green, "really suspicious" red, and an unreviewed sale
         grey — because that is not a decision yet. */
      cell: (row, base) =>
        row.review
          ? text(t(REVIEW_LABEL[row.review.status]), {
              textColor: row.review.status === 'justified' ? GOOD : BAD,
              fontWeight: 'bold',
              ...base,
            })
          : text(t('sales.review.new'), { textColor: MUTED, ...base }),
    },
    {
      key: 'decisionReason',
      header: t('sales.col.decisionReason'),
      tip: 'sales.exportSuspicious.tip.decisionReason',
      width: 16,
      /* No value leaves the cell EMPTY — an em dash in every row of a column
         that is mostly empty is just noise. */
      cell: (row, base) =>
        text(row.review?.reason ? t(REASON_LABEL[row.review.reason]) : null, base),
    },
    {
      key: 'note',
      header: t('sales.col.note'),
      tip: 'sales.exportSuspicious.tip.note',
      width: 34,
      cell: (row, base) => text(row.review?.note, { wrap: true, ...base }),
    },
  ]
}

/* ── Sheet 1: the summary ─────────────────────────────────── */

/** How many columns the summary sheet has; notes span all of them. */
const SUMMARY_SPAN = 6
const SUMMARY_WIDTHS = [34, 16, 24, 20, 20, 20]
/** Their combined width in characters, for the note-height arithmetic. A
 *  little under the sum of `SUMMARY_WIDTHS`: a word that wraps whole leaves
 *  the line short. */
const SUMMARY_LINE = 120

/**
 * The summary: title → warning → figures → decision cut → rule cut.
 *
 * No merged "cards". A merged cell breaks both sorting and copying in Excel,
 * and files built that way are exactly the ones that look machine-generated.
 * Label in the left column, figure beside it, note to its right.
 */
function summarySheet(
  rows: ComplianceItem[],
  summary: ComplianceSummary | undefined,
  meta: Meta,
  windowDays: number | undefined,
): { data: SheetData; widths: number[] } {
  const decisions = countDecisions(rows)
  const rules = countRules(rows)
  const clients = new Set(rows.map((row) => row.partner_code)).size

  /* ⚠️ AN EMPLOYEE AND AN UNLINKED BRANCH ARE NOT ADDED UP. They were once
     counted together as `agent_id ?? branch`, which produced "Employees
     concerned: 28" when there are 21 employees and 7 unlinked SAP names.
     Measured (August 2026): of 791 suspicious sales, 288 belong to nobody —
     they cannot be explained by a per-employee cut at all, and hiding that
     would make the report untrustworthy. */
  const agents = new Set(rows.filter((row) => row.agent_id).map((row) => row.agent_id)).size
  const unlinkedBranches = new Set(
    rows.filter((row) => !row.agent_id).map((row) => row.branch ?? ''),
  ).size
  const unlinkedSales = rows.filter((row) => !row.agent_id).length

  /** One figure: label · number · note. */
  const metric = (label: string, value: CellObject, hint?: string): Row => [
    text(label, { fontSize: 11, textColor: INK }),
    { ...value, fontWeight: 'bold', fontSize: 14 },
    ...(hint ? span(text(hint, { fontSize: 10, textColor: MUTED }), SUMMARY_SPAN - 2) : []),
  ]

  const data: SheetData = [
    span(text(t('sales.exportSuspicious.title'), TITLE), SUMMARY_SPAN),
    /* ⚠️ THE WARNING IS IN THE FILE ITSELF: this list does not accuse anybody.
       On screen it sits under the heading; the file leaves the screen and
       passes from hand to hand, and without the sentence it reads as a list of
       accusations. */
    note(t('sales.subtitle'), { fontSize: 10, textColor: WARN }, SUMMARY_SPAN, SUMMARY_LINE),
    span(text(meta.period, META), SUMMARY_SPAN),
    span(text(meta.scope, META), SUMMARY_SPAN),
    span(text(meta.generated, META), SUMMARY_SPAN),
    [],
    span(text(t('sales.exportSuspicious.metrics'), SECTION), SUMMARY_SPAN),
    metric(
      t('sales.exportSuspicious.count'),
      num(rows.length, { textColor: BAD }),
      summary ? t('sales.exportSuspicious.ofTotal', { count: summary.total }) : undefined,
    ),
  ]

  /* The share only means anything with the summary: its divisor is the number
     of sales in the WHOLE selection, which is not in `rows`. */
  if (summary?.total) {
    data.push(
      metric(
        t('sales.exportSuspicious.share'),
        pct((rows.length / summary.total) * 100, { textColor: BAD }),
      ),
    )
  }

  data.push(
    metric(
      t('sales.col.amountUsd'),
      money(sumUsd(rows), { textColor: INK }),
      t('sales.exportSuspicious.amountHint'),
    ),
    metric(
      t('sales.exportSuspicious.agents'),
      num(agents, { textColor: INK }),
      unlinkedSales
        ? t('sales.exportSuspicious.unlinked', {
            branches: unlinkedBranches,
            sales: unlinkedSales,
          })
        : undefined,
    ),
    metric(t('sales.exportSuspicious.clients'), num(clients, { textColor: INK })),
    [],
    span(text(t('sales.exportSuspicious.decisions'), SECTION), SUMMARY_SPAN),
    metric(
      t('sales.review.new'),
      num(decisions.new, { textColor: MUTED }),
      t('sales.exportSuspicious.newHint'),
    ),
    metric(
      t('sales.review.justified'),
      num(decisions.justified, { textColor: GOOD }),
      t('sales.decision.justifiedHint'),
    ),
    metric(
      t('sales.review.confirmed'),
      num(decisions.confirmed, { textColor: BAD }),
      t('sales.decision.confirmedHint'),
    ),
    [],
    span(text(t('sales.exportSuspicious.rules'), SECTION), SUMMARY_SPAN),
  )

  /* The code as the label (the table prints the same thing), the full sentence
     beside it: "R1" on its own explains nothing. */
  RULES.forEach((rule) => {
    data.push([
      text(rule, { fontWeight: 'bold', textColor: WARN, fontSize: 11 }),
      num(rules[rule], { fontWeight: 'bold', fontSize: 14, textColor: INK }),
      ...span(
        text(ruleText(rule, windowDays), { fontSize: 10, textColor: MUTED }),
        SUMMARY_SPAN - 2,
      ),
    ])
  })

  data.push(
    note(
      t('sales.exportSuspicious.rulesNote'),
      { fontSize: 10, textColor: MUTED },
      SUMMARY_SPAN,
      SUMMARY_LINE,
    ),
  )

  return { data, widths: SUMMARY_WIDTHS }
}

/* ── Sheet 2: the sales ───────────────────────────────────── */

function salesSheet(rows: ComplianceItem[], meta: Meta): { data: SheetData; widths: number[] } {
  const cols = columns()
  const width = cols.length

  const data: SheetData = [
    ...head(t('sales.export.sheetSales'), meta, width),
    cols.map((column) => text(column.header, { ...HEADER, align: column.align ?? 'left' })),
  ]

  rows.forEach((row) => {
    /* No zebra — a hairline under each row instead (`shared/lib/xlsx.ts`). */
    data.push(cols.map((column) => column.cell(row, RULE)))
  })

  if (!rows.length) {
    data.push(emptyRow(width))
    return { data, widths: cols.map((column) => column.width) }
  }

  /* "Jami" sits INSIDE the table, as its last row: on a separate sheet it
     would mean switching sheets to compare against it.
     ⚠️ The document-currency column is deliberately EMPTY — the rows hold both
     som and dollars and their sum is not a number. */
  data.push(
    cols.map((column) => {
      if (column.key === 'date') return text(t('sales.export.totalRow'), TOTAL)
      /* The number of sales stands beside the label and reads as "Jami 137".
         The column itself is text (operation numbers), so this figure cannot
         be mistaken for a sum. */
      if (column.key === 'operation') return num(rows.length, TOTAL)
      if (column.key === 'amountUsd') return money(sumUsd(rows), { ...TOTAL, textColor: BAD })
      return { ...TOTAL }
    }),
  )

  return { data, widths: cols.map((column) => column.width) }
}

/* ── Sheet 3: by employee ─────────────────────────────────── */

interface AgentStat {
  name: string
  /** Their sales in the WHOLE selection — known only from the summary. `null`
   *  leaves the share uncomputed as well. */
  sales: number | null
  suspicious: number
  new: number
  justified: number
  confirmed: number
  /** The dollar total of the suspicious sales — from `rows`. */
  usd: number
  /**
   * How many CUSTOMERS this employee sold to in the period.
   *
   * `null` — unknowable: no timeline was fetched, or it was fetched for
   * suspicious customers only. Then the cell stays EMPTY rather than showing
   * a zero, which would be the lie "not a single customer".
   */
  clients: number | null
  /** How many of them carry a suspicious sale — ALWAYS from `rows`. */
  suspiciousClients: number
}

/** The part kept in `own`: the customer counts come from separate sets, not
 *  from the rows. */
type OwnStat = Omit<AgentStat, 'clients' | 'suspiciousClients'>

/**
 * Was the timeline taken over the WHOLE selection?
 *
 * ⚠️ WHY THE QUESTION. `only_suspicious` defaults to on in the request, and
 * then the list holds only customers that have a suspicion against them. "How
 * many customers did this employee sell to" cannot be taken from such a list:
 * the answer would always equal "suspicious customers", i.e. the column would
 * repeat itself and lie.
 *
 * The marker is the presence of a customer with NO suspicion. A cut list
 * (`truncated`) is no good either: its figure is incomplete.
 */
function timelineIsFull(timeline: ComplianceTimeline | undefined): boolean {
  if (!timeline || timeline.truncated) return false
  return (timeline.clients ?? []).some((client) => client.suspicious_count === 0)
}

/**
 * Employee → the customer codes they sold to, FROM THE TIMELINE.
 *
 * Keyed on the NAME, not on `agent_id`: the timeline response carries no uuid,
 * only the employee's name. Two employees with the same name collapse into one
 * row — a price paid on purpose: the suspicious cut is still computed by
 * `agent_id`, and this column only answers "how many customers".
 *
 * ⚠️ ONLY SALE EVENTS COUNT. A call has nothing to do with "customers sold
 * to"; letting a customer who was spoken to but never bought into this figure
 * would deflate the share (suspicious / all) artificially.
 */
function clientsByAgent(timeline: ComplianceTimeline): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>()
  ;(timeline.clients ?? []).forEach((client) => {
    ;(client.events ?? []).forEach((event) => {
      if (event.kind !== 'sale') return
      const name = event.agent_name ?? t('sales.noAgent')
      const codes = map.get(name) ?? new Set<string>()
      codes.add(client.partner_code)
      map.set(name, codes)
    })
  })
  return map
}

/**
 * The per-employee cut.
 *
 * The counts come from the summary (`summary.agents`), the money from `rows`:
 * the summary carries no money, and the file itself holds every suspicious
 * row. Without a summary the sheet is still built — everything then comes from
 * the rows and the "Savdolar" column stays empty, because the number of sales
 * in the whole selection cannot be derived from the suspicious ones.
 *
 * ⚠️ EMPLOYEES WITH NO SUSPICIOUS SALE STAY IN THE LIST. "Who has the most" is
 * only answerable by comparison: 5 out of 200 and 5 out of 12 are the same
 * figure and a different story.
 */
function agentStats(
  rows: ComplianceItem[],
  summary: ComplianceSummary | undefined,
  timeline: ComplianceTimeline | undefined,
): AgentStat[] {
  /** Sales with no employee also come out as ONE row: an unlinked name is a
   *  state, not missing data. */
  const key = (agentId: string | null | undefined) => agentId ?? ''
  const own = new Map<string, OwnStat>()
  /** Customers with a suspicious sale, by `agent_id`.
   *
   *  ⚠️ NOT TAKEN FROM THE TIMELINE. The timeline may be cut (`max_clients`),
   *  and then "Xodimlar bo'yicha" and "Mijozlar bo'yicha" would show figures
   *  that contradict each other. `rows` is the file's own evidence — every
   *  other sheet comes from it too. */
  const ownClients = new Map<string, Set<string>>()

  rows.forEach((row) => {
    const id = key(row.agent_id)
    const stat = own.get(id) ?? {
      name: row.agent_name ?? t('sales.noAgent'),
      sales: null,
      suspicious: 0,
      new: 0,
      justified: 0,
      confirmed: 0,
      usd: 0,
    }
    stat.suspicious += 1
    stat.usd += row.amount_usd ?? 0
    if (!row.review) stat.new += 1
    else if (row.review.status === 'justified') stat.justified += 1
    else stat.confirmed += 1
    own.set(id, stat)

    const codes = ownClients.get(id) ?? new Set<string>()
    codes.add(row.partner_code)
    ownClients.set(id, codes)
  })

  /* The whole customer count is known only from a full timeline — otherwise
     the column stays empty (the reason is on `AgentStat.clients`). */
  const byName = timelineIsFull(timeline) && timeline ? clientsByAgent(timeline) : null

  const stats: AgentStat[] = summary?.agents?.length
    ? summary.agents.map((agent: AgentBreakdown) => {
        const name = agent.agent_name ?? t('sales.noAgent')
        const id = key(agent.agent_id)
        return {
          name,
          sales: agent.sales,
          suspicious: agent.suspicious,
          new: agent.new,
          justified: agent.justified,
          confirmed: agent.confirmed,
          usd: own.get(id)?.usd ?? 0,
          clients: byName ? (byName.get(name)?.size ?? 0) : null,
          suspiciousClients: ownClients.get(id)?.size ?? 0,
        }
      })
    : [...own.entries()].map(([id, stat]) => ({
        ...stat,
        clients: byName ? (byName.get(stat.name)?.size ?? 0) : null,
        suspiciousClients: ownClients.get(id)?.size ?? 0,
      }))

  return stats.sort((a, b) => b.suspicious - a.suspicious || b.usd - a.usd)
}

function agentsSheet(
  rows: ComplianceItem[],
  summary: ComplianceSummary | undefined,
  meta: Meta,
  timeline: ComplianceTimeline | undefined,
): { data: SheetData; widths: number[] } {
  const stats = agentStats(rows, summary, timeline)
  const headers: [string, number, 'left' | 'right'][] = [
    [t('sales.col.agent'), 28, 'left'],
    [t('sales.col.sales'), 12, 'right'],
    [t('sales.verdict.suspicious'), 14, 'right'],
    [t('sales.exportSuspicious.share'), 14, 'right'],
    [t('sales.exportSuspicious.suspiciousAmount'), 18, 'right'],
    /* The customer cut sits AFTER the sales cut: "5 of 200 sales are
       suspicious" and "3 of 40 customers have a suspicion" are two different
       questions and must not blur into one. */
    [t('sales.exportSuspicious.clientsCol'), 12, 'right'],
    [t('sales.exportSuspicious.suspiciousClients'), 18, 'right'],
    [t('sales.review.new'), 14, 'right'],
    [t('sales.review.justified'), 14, 'right'],
    [t('sales.review.confirmed'), 20, 'right'],
  ]

  const data: SheetData = [
    ...head(t('sales.exportSuspicious.sheetAgents'), meta, headers.length),
    headers.map(([label, , align]) => text(label, { ...HEADER, align })),
  ]

  stats.forEach((stat) => {
    data.push([
      text(stat.name, RULE),
      num(stat.sales, { textColor: MUTED, ...RULE }),
      num(stat.suspicious, {
        fontWeight: 'bold',
        textColor: stat.suspicious ? BAD : GOOD,
        ...RULE,
      }),
      pct(stat.sales ? (stat.suspicious / stat.sales) * 100 : null, {
        textColor: stat.suspicious ? BAD : GOOD,
        ...RULE,
      }),
      money(stat.usd, RULE),
      num(stat.clients, { textColor: MUTED, ...RULE }),
      num(stat.suspiciousClients, {
        textColor: stat.suspiciousClients ? BAD : GOOD,
        ...RULE,
      }),
      num(stat.new, { textColor: MUTED, ...RULE }),
      num(stat.justified, { textColor: stat.justified ? GOOD : undefined, ...RULE }),
      num(stat.confirmed, { textColor: stat.confirmed ? BAD : undefined, ...RULE }),
    ])
  })

  if (!stats.length) {
    data.push(emptyRow(headers.length))
    return { data, widths: headers.map(([, width]) => width) }
  }

  const sum = (pick: (stat: AgentStat) => number) =>
    stats.reduce((acc, stat) => acc + pick(stat), 0)
  /* The sales column stays empty without a summary: a zero there would be the
     lie "no sales were made". */
  const sales = stats.some((stat) => stat.sales != null) ? sum((stat) => stat.sales ?? 0) : null
  const suspicious = sum((stat) => stat.suspicious)

  /* ⚠️ THE CUSTOMER COLUMNS ARE NOT ADDED UP. A customer worked by two
     employees appears in both rows, and the sum would count them twice. On the
     total row they are counted UNIQUELY — so the figure matches the one on
     "Mijozlar bo'yicha" exactly. */
  const clients =
    timelineIsFull(timeline) && timeline
      ? (timeline.clients ?? []).filter((client) => client.sales_count > 0).length
      : null
  const suspiciousClients = new Set(rows.map((row) => row.partner_code)).size

  data.push([
    text(t('sales.export.totalRow'), TOTAL),
    num(sales, TOTAL),
    num(suspicious, { ...TOTAL, textColor: BAD }),
    pct(sales ? (suspicious / sales) * 100 : null, { ...TOTAL, textColor: BAD }),
    money(
      sum((stat) => stat.usd),
      TOTAL,
    ),
    num(clients, TOTAL),
    num(suspiciousClients, { ...TOTAL, textColor: BAD }),
    num(
      sum((stat) => stat.new),
      TOTAL,
    ),
    num(
      sum((stat) => stat.justified),
      TOTAL,
    ),
    num(
      sum((stat) => stat.confirmed),
      TOTAL,
    ),
  ])

  return { data, widths: headers.map(([, width]) => width) }
}

/* ── Sheet 4: by customer ─────────────────────────────────── */

interface ClientStat {
  code: string
  name: string | null
  phone: string | null
  count: number
  usd: number
  /** `YYYY-MM-DD` — sorts correctly as a string too. */
  first: string
  last: string
  agents: string[]
}

/**
 * The per-customer cut — "whose customer is this".
 *
 * WHY IT EXISTS. The employee cut asks "who has the most"; this one answers a
 * different question: when ten suspicious sales pile up on ONE customer, the
 * cause is not the employee — that customer is worked OFF the phone (contract
 * §5: the distribution of reasons measures the system's own shortcoming).
 *
 * Grouped by CODE, not by phone or name: the name can be empty in a SAP
 * export, and one customer has several numbers.
 */
function clientStats(rows: ComplianceItem[]): ClientStat[] {
  const map = new Map<string, ClientStat>()

  rows.forEach((row) => {
    const stat = map.get(row.partner_code) ?? {
      code: row.partner_code,
      name: row.partner_name ?? null,
      phone: row.phone ?? null,
      count: 0,
      usd: 0,
      first: row.occurred_on,
      last: row.occurred_on,
      agents: [],
    }
    stat.count += 1
    stat.usd += row.amount_usd ?? 0
    if (row.occurred_on < stat.first) stat.first = row.occurred_on
    if (row.occurred_on > stat.last) stat.last = row.occurred_on
    /* The first name and phone found are kept: a later row may have them
       empty, and an empty value would erase a complete one. */
    stat.name ??= row.partner_name ?? null
    stat.phone ??= row.phone ?? null
    /* The same name as on screen: `sellerName` falls back to SAP's own wording,
       where the employee is usually written as a territory. */
    const seller = sellerName(row)
    if (seller && !stat.agents.includes(seller)) stat.agents.push(seller)
    map.set(row.partner_code, stat)
  })

  return [...map.values()].sort((a, b) => b.count - a.count || b.usd - a.usd)
}

/** The employees in one cell. More than three collapse into "+N": the full
 *  list would turn the cell into a paragraph, and who they are is on the
 *  "Savdolar" sheet row by row anyway. */
function sellers(names: string[]): string {
  if (names.length <= 3) return names.join(', ')
  return [
    ...names.slice(0, 3),
    t('sales.exportSuspicious.andMore', { count: names.length - 3 }),
  ].join(', ')
}

function clientsSheet(rows: ComplianceItem[], meta: Meta): { data: SheetData; widths: number[] } {
  const stats = clientStats(rows)
  const headers: [string, number, 'left' | 'right'][] = [
    [t('sales.col.code'), 14, 'left'],
    [t('sales.col.client'), 32, 'left'],
    [t('sales.col.phone'), 16, 'left'],
    [t('sales.verdict.suspicious'), 14, 'right'],
    [t('sales.col.amountUsd'), 16, 'right'],
    [t('sales.exportSuspicious.firstSale'), 14, 'right'],
    [t('sales.exportSuspicious.lastSale'), 14, 'right'],
    [t('sales.exportSuspicious.sellers'), 30, 'left'],
  ]

  const data: SheetData = [
    ...head(t('sales.exportSuspicious.sheetClients'), meta, headers.length),
    headers.map(([label, , align]) => text(label, { ...HEADER, align })),
  ]

  stats.forEach((stat) => {
    data.push([
      text(stat.code, { textColor: MUTED, ...RULE }),
      text(stat.name, RULE),
      text(stat.phone, RULE),
      num(stat.count, { fontWeight: 'bold', textColor: BAD, ...RULE }),
      money(stat.usd, RULE),
      date(stat.first, { align: 'center', ...RULE }),
      date(stat.last, { align: 'center', ...RULE }),
      text(sellers(stat.agents), { textColor: MUTED, ...RULE }),
    ])
  })

  if (!stats.length) {
    data.push(emptyRow(headers.length))
    return { data, widths: headers.map(([, width]) => width) }
  }

  data.push([
    text(t('sales.export.totalRow'), TOTAL),
    /* How many CUSTOMERS, in the column next to the number of sales — the two
       read together: "12 customers, 41 sales". */
    num(stats.length, TOTAL),
    { ...TOTAL },
    num(rows.length, { ...TOTAL, textColor: BAD }),
    money(sumUsd(rows), TOTAL),
    { ...TOTAL },
    { ...TOTAL },
    { ...TOTAL },
  ])

  return { data, widths: headers.map(([, width]) => width) }
}

/* ── Sheet 5: the timeline ────────────────────────────────── */

/**
 * THE TIMELINE SHEET — the most valuable part of this file.
 *
 * WHY IT EXISTS. The other sheets give FIGURES: how many are suspicious, who
 * has the most, whose customers they are. They answer "45", but not "what
 * happened?". A manager — a director especially — decides with the EYE rather
 * than by reading a table: with conversations and sales on one axis, the
 * pattern "sale → sale → sale, nothing in between" shows itself. The screen
 * already draws that axis (`SaleCardModal`), but around ONE sale; here it is
 * the whole period and the whole employee.
 *
 * ⚠️ THE SHEET IS A FLAT TABLE. A grouped "tree" would look prettier, but in
 * Excel sorting and filtering are the manager's main tools and they only work
 * on a flat table. So the customer's code and name are repeated on EVERY row
 * (left blank, a filter would lose them), and a group is marked by a heading
 * row alone — bold, lightly filled, with a hairline above it.
 *
 * ⚠️ THE ROWS ARE NOT RE-SORTED. The server orders them by date and puts the
 * CALL first within a day — which is exactly how the rules compute. Re-sorting
 * by `at` here would invert that: a sale's `at` is 00:00 of its day, so it
 * would jump ahead of every conversation that day (`api.ts::useSaleTimeline`
 * makes the same promise for the screen).
 */

/**
 * One conversation's length — `8:42`.
 *
 * ⚠️ `[m]` in square brackets: a plain `m` wraps back to zero after 60
 * minutes, and a half-hour conversation would read as `0:12`. The cell holds a
 * NUMBER (not text), so Excel can sort it.
 */
const DURATION = '[m]:ss'
/** Excel counts a day as 1, so seconds are converted into that unit. */
const DAY_SECONDS = 86_400
/**
 * A call's TIME — without its date.
 *
 * The date is in the column beside it; writing it twice would only widen the
 * column. The cell is built by `datetime()` itself (only its format is
 * swapped): the rule for re-expressing the Tashkent wall clock lives in
 * `shared/lib/xlsx` and must not be repeated — a second copy is how the file
 * ends up five hours out.
 */
const TIME = 'hh:mm'

/** The width of the warning line on the timeline sheet, in characters. */
const TIMELINE_LINE = 150

/**
 * The customer's heading row.
 *
 * ⚠️ NO MERGED CELLS. A merged cell destroys both sorting and filtering in
 * Excel, and those are the whole point of this sheet. What separates a group
 * for the eye is bold text, a light fill and a hairline above.
 */
const CLIENT_HEAD: CellStyle = {
  fontWeight: 'bold',
  backgroundColor: BAND,
  topBorderStyle: 'thin',
  topBorderColor: NAVY,
}

/** A duration cell — seconds into Excel's own unit. */
function duration(seconds: number | null | undefined, style: CellStyle = {}): CellObject {
  if (seconds == null) return { ...style }
  return { value: seconds / DAY_SECONDS, type: Number, format: DURATION, ...style }
}

/**
 * ⚠️ THE WIRE VALUE IS `incoming`/`outgoing`, NOT the source's
 * `inbound`/`outbound`.
 *
 * `core/enums.py` states it outright — "ours, not BonviZvonki's" — and the
 * timeline sends `CallDirection.value` straight through. Carrying the source's
 * comparison across would have made every call read as outgoing, silently: the
 * cell would still have been filled, with the wrong word.
 */
const INCOMING: CallDirection = 'incoming'

/**
 * The same map the call list renders from.
 *
 * Widened to `string` because a timeline event's `direction` is a plain
 * `string` on the wire (`TimelineEventOut`), so the lookup may MISS — and an
 * unknown value leaves the part out rather than printing a dotted identifier
 * into a spreadsheet.
 */
const CALL_DIRECTION_LABEL: Record<string, MessageKey> = DIRECTION_LABEL

interface TimelineBlock {
  /** WHOSE work this customer is — the group heading. */
  agent: string
  client: TimelineClient
}

/**
 * Which employee's group a customer falls into.
 *
 * Several employees may have worked one customer. The group is whoever SOLD
 * the most: the sheet asks "which customers did this employee work", and a
 * sale is the result of that work.
 *
 * ⚠️ The row's own "Xodim" column still names the event's REAL owner, so a
 * conversation by somebody else is visible inside the group — and it should
 * be: "Ali made the sale, Vali did the talking" is a story of its own.
 */
function blockAgent(client: TimelineClient): string {
  const bySales = new Map<string, number>()
  ;(client.events ?? []).forEach((event) => {
    if (event.kind !== 'sale') return
    const name = event.agent_name ?? t('sales.noAgent')
    bySales.set(name, (bySales.get(name) ?? 0) + 1)
  })

  const top = [...bySales.entries()].sort((a, b) => b[1] - a[1])[0]
  /* A customer with no sale (conversations only) does not go without a group
     either: the first name in the response's `agents` list is taken. */
  return top?.[0] ?? (client.agents ?? [])[0] ?? t('sales.noAgent')
}

/**
 * The row order: EMPLOYEE → CUSTOMER → DATE.
 *
 * Employees start with whoever has the most suspicious sales — EXACTLY the
 * logic of "Xodimlar bo'yicha". Two sheets in two orders could not be read
 * side by side.
 */
function timelineBlocks(timeline: ComplianceTimeline): TimelineBlock[] {
  const blocks: TimelineBlock[] = (timeline.clients ?? []).map((client) => ({
    agent: blockAgent(client),
    client,
  }))

  const rank = new Map<string, { suspicious: number; sales: number }>()
  blocks.forEach(({ agent, client }) => {
    const stat = rank.get(agent) ?? { suspicious: 0, sales: 0 }
    stat.suspicious += client.suspicious_count
    stat.sales += client.sales_count
    rank.set(agent, stat)
  })
  const of = (agent: string) => rank.get(agent) ?? { suspicious: 0, sales: 0 }

  return blocks.sort((a, b) => {
    const x = of(a.agent)
    const y = of(b.agent)
    return (
      y.suspicious - x.suspicious ||
      y.sales - x.sales ||
      a.agent.localeCompare(b.agent) ||
      b.client.suspicious_count - a.client.suspicious_count ||
      b.client.amount_usd - a.client.amount_usd ||
      a.client.partner_code.localeCompare(b.client.partner_code)
    )
  })
}

/**
 * The detail of a call row: "Kiruvchi · Javob berilgan".
 *
 * ⚠️ THE ANSWER STATE IS WRITTEN IN THE SCREEN'S OWN WORDS. A single word,
 * "unanswered", would hide WHO failed to pick up — and the employee not
 * answering and the customer not answering are entirely different stories.
 *
 * ⚠️ The source's third branch — "unknown" — is dropped rather than ported.
 * The server computes `answered` as `disposition == ANSWERED`, so a call event
 * always carries a boolean; it is nullable on the wire and never null in
 * practice, and there is no catalogue word for a state that cannot occur.
 */
function callDetail(event: TimelineEvent): string {
  const label = event.direction ? CALL_DIRECTION_LABEL[event.direction] : undefined
  const way = label ? t(label) : null
  const answer =
    event.answered === false
      ? event.direction === INCOMING
        ? t('clients.dirNoAnswer')
        : t('clients.dirNotPicked')
      : event.answered
        ? t('calls.disposition.answered')
        : null

  return [way, answer].filter(Boolean).join(' · ')
}

/**
 * The detail of a sale row: the document and the operation number.
 *
 * The manager finds the row in SAP by exactly those two, so both are written
 * and both are labelled — bare numbers give no clue which is which. Last comes
 * R1's evidence: how many days before the sale the last conversation was.
 */
function saleDetail(event: TimelineEvent): string {
  return [
    event.doc_number ? `${t('sales.col.document')} ${event.doc_number}` : null,
    event.external_id ? `${t('sales.col.operation')} ${event.external_id}` : null,
    event.days_before != null
      ? t('sales.exportSuspicious.lastCallDays', { count: event.days_before })
      : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** The customer heading — code, name, phone, counts and money. The columns
 *  keep their places: this is a row of the flat table too. */
function clientHeadRow(agent: string, client: TimelineClient): Row {
  const totals = t('sales.exportSuspicious.clientTotals', {
    sales: client.sales_count,
    suspicious: client.suspicious_count,
    calls: client.calls_count,
  })

  return [
    text(agent, CLIENT_HEAD),
    text(client.partner_code, CLIENT_HEAD),
    text(client.partner_name, CLIENT_HEAD),
    { ...CLIENT_HEAD }, // Sana
    { ...CLIENT_HEAD }, // Vaqt
    { ...CLIENT_HEAD }, // Hodisa
    /* The phone and the counts share one cell: the columns to its right are
       empty on a heading row, so the text runs across them. */
    text([client.phone, totals].filter(Boolean).join(' · '), {
      ...CLIENT_HEAD,
      textColor: client.suspicious_count ? BAD : MUTED,
    }),
    { ...CLIENT_HEAD }, // Davomiyligi
    money(client.amount_usd, CLIENT_HEAD),
    { ...CLIENT_HEAD }, // Xulosa
    { ...CLIENT_HEAD }, // Buzilgan qoidalar
  ]
}

/** One event on the axis — a call or a sale. */
function eventRow(event: TimelineEvent, client: TimelineClient): Row {
  const sale = event.kind === 'sale'
  const bad = sale && event.verdict === 'suspicious'
  /* COLOUR IS MEANING. Red only on a suspicious sale. A clean sale and a call
     both stay grey and are told apart by WEIGHT — which is what makes the
     pattern "sale → sale → sale, no grey row in between" readable by eye. */
  const tone = bad ? BAD : MUTED
  const strong: CellStyle = sale ? { fontWeight: 'bold' } : {}
  const rules = event.broken_rules ?? []

  return [
    /* The event's REAL owner, not the employee in the group heading: somebody
       else's conversation has to be visible in exactly this column. */
    text(event.agent_name ?? t('sales.noAgent'), {
      textColor: tone,
      ...strong,
      ...RULE,
    }),
    text(client.partner_code, { textColor: MUTED, ...RULE }),
    text(client.partner_name, { textColor: MUTED, ...RULE }),
    date(event.at, { align: 'center', textColor: tone, ...RULE }),
    /* ⚠️ THE TIME IS ON CALLS ONLY. SAP gives a sale no clock and `at` holds
       00:00 of that day; writing it would be the lie "the sale happened at
       midnight". */
    sale
      ? { ...RULE }
      : datetime(event.at, {
          format: TIME,
          align: 'center',
          textColor: MUTED,
          ...RULE,
        }),
    text(sale ? t('sales.exportSuspicious.eventSale') : t('sales.exportSuspicious.eventCall'), {
      textColor: tone,
      ...strong,
      ...RULE,
    }),
    text(sale ? saleDetail(event) : callDetail(event), {
      textColor: MUTED,
      ...RULE,
    }),
    /* An unanswered call lasted 0 seconds, and writing "0:00" would be a lie —
       no conversation took place at all. */
    !sale && event.answered !== false
      ? duration(event.duration_sec, { align: 'right', textColor: MUTED, ...RULE })
      : { ...RULE },
    sale ? money(event.amount_usd, { textColor: tone, ...strong, ...RULE }) : { ...RULE },
    sale && event.verdict
      ? text(t(VERDICT_LABEL[event.verdict]), {
          textColor: tone,
          ...strong,
          ...RULE,
        })
      : { ...RULE },
    sale
      ? text(rules.join(', '), {
          align: 'center',
          textColor: rules.length ? WARN : undefined,
          ...RULE,
        })
      : { ...RULE },
  ]
}

function timelineSheet(
  timeline: ComplianceTimeline,
  meta: Meta,
): { data: SheetData; widths: number[]; sticky: number } {
  const headers: [string, number, 'left' | 'center' | 'right'][] = [
    [t('sales.col.agent'), 22, 'left'],
    [t('sales.col.code'), 13, 'left'],
    [t('sales.col.client'), 28, 'left'],
    [t('sales.col.date'), 12, 'center'],
    [t('sales.exportSuspicious.time'), 9, 'center'],
    [t('sales.exportSuspicious.event'), 13, 'left'],
    [t('sales.exportSuspicious.detail'), 40, 'left'],
    [t('calls.colDuration'), 12, 'right'],
    [t('sales.col.amountUsd'), 14, 'right'],
    [t('sales.col.verdict'), 15, 'left'],
    [t('sales.col.rules'), 15, 'center'],
  ]
  const width = headers.length

  const data: SheetData = [...head(t('sales.exportSuspicious.sheetTimeline'), meta, width)]

  /* A cut list is NOT passed over in silence: a customer missing from the
     sheet would read as "no suspicion here", when they simply did not fit. */
  if (timeline.truncated) {
    data.push(
      note(
        t('sales.exportSuspicious.truncated', { count: (timeline.clients ?? []).length }),
        { fontSize: 10, textColor: WARN },
        width,
        TIMELINE_LINE,
      ),
      [],
    )
  }

  data.push(headers.map(([label, , align]) => text(label, { ...HEADER, align })))
  /* The frozen rows — the header block + (the warning) + the column names.
     Writing the number by hand would push the table down by a row the moment
     the warning appears. */
  const sticky = data.length

  const blocks = timelineBlocks(timeline)
  blocks.forEach(({ agent, client }) => {
    data.push(clientHeadRow(agent, client))
    ;(client.events ?? []).forEach((event) => {
      data.push(eventRow(event, client))
    })
  })

  if (!blocks.length) data.push(emptyRow(width))

  return { data, widths: headers.map(([, columnWidth]) => columnWidth), sticky }
}

/* ── Sheet 6: the glossary ────────────────────────────────── */

/** The second column of the glossary — the width the text wraps at. */
const GLOSSARY_LINE = 118

/**
 * The terms sheet.
 *
 * WHY IT EXISTS. On screen every column carries an explanation (it appears
 * when the header is hovered); in the file it does not. The file travels by
 * email and whoever opens it may never have seen the screen — "Orasidagi
 * suhbatlar" or "R2" is knowable only from here.
 *
 * Last of all comes the MOST important warning: a sale has no clock. Without
 * it the line "0 days before the sale" is read the wrong way round.
 */
function glossarySheet(
  meta: Meta,
  windowDays: number | undefined,
  /** Whether the file has a timeline sheet. Without one its columns are not
   *  explained here either: the glossary of a sheet that does not exist only
   *  sends the reader hunting for it. */
  hasTimeline: boolean,
): { data: SheetData; widths: number[] } {
  const data: SheetData = [
    ...head(t('sales.exportSuspicious.sheetGlossary'), meta, 2),
    [
      text(t('sales.exportSuspicious.term'), { ...HEADER, height: 24, wrap: false }),
      text(t('sales.exportSuspicious.definition'), { ...HEADER, height: 24, wrap: false }),
    ],
    /* Straight off the column definitions, so a column added to the table
       cannot end up unexplained here. */
    ...glossaryRows(columns().map((column): [string, string] => [column.header, t(column.tip)])),
    [],
    /* The TWO columns of "Xodimlar bo'yicha" that the table does not have.
       They are not under `sales.col.*` because these figures are computed in
       this file alone — the screen has no such cut. */
    span(text(t('sales.exportSuspicious.sheetAgents'), SECTION), 2),
    ...glossaryRows([
      [
        t('sales.exportSuspicious.clientsCol'),
        t('sales.exportSuspicious.tip.clientsCol'),
      ],
      [
        t('sales.exportSuspicious.suspiciousClients'),
        t('sales.exportSuspicious.tip.suspiciousClients'),
      ],
    ]),
    ...(hasTimeline
      ? [
          [],
          span(text(t('sales.exportSuspicious.sheetTimeline'), SECTION), 2),
          ...glossaryRows([
            [t('sales.exportSuspicious.event'), t('sales.exportSuspicious.tip.event')],
            [t('sales.exportSuspicious.time'), t('sales.exportSuspicious.tip.time')],
            [t('sales.exportSuspicious.detail'), t('sales.exportSuspicious.tip.detail')],
            [t('calls.colDuration'), t('sales.exportSuspicious.tip.duration')],
          ]),
          note(
            t('sales.exportSuspicious.timelineNote'),
            { fontSize: 10, textColor: INK },
            2,
            GLOSSARY_LINE,
          ),
        ]
      : []),
    [],
    span(text(t('sales.exportSuspicious.rules'), SECTION), 2),
    /* R1's window comes from the response: if the setting changes later, an
       old file still states the threshold it was built with. */
    ...glossaryRows(RULES.map((rule): [string, string] => [rule, ruleText(rule, windowDays)])),
    [],
    span(text(t('sales.exportSuspicious.decisions'), SECTION), 2),
    ...glossaryRows([
      [t('sales.review.new'), t('sales.exportSuspicious.newHint')],
      [t('sales.review.justified'), t('sales.decision.justifiedHint')],
      [t('sales.review.confirmed'), t('sales.decision.confirmedHint')],
    ]),
    [],
    span(text(t('sales.exportSuspicious.timeTitle'), SECTION), 2),
  ]

  /* The window sentence is only written when the window is known — a printed
     `{count}` would be worse than a missing line. */
  if (windowDays != null) {
    data.push(
      note(
        t('sales.windowNote', { count: windowDays }),
        { fontSize: 10, textColor: INK },
        2,
        GLOSSARY_LINE,
      ),
    )
  }

  data.push(
    note(
      t('sales.exportSuspicious.timeWarning'),
      { fontSize: 10, textColor: WARN },
      2,
      GLOSSARY_LINE,
    ),
  )

  return { data, widths: [30, 100] }
}

/* ── Entry point ──────────────────────────────────────────── */

export interface SuspiciousExportOptions {
  /** The caller has already fetched with `verdict=suspicious`; the builder
   *  filters again anyway — see `buildSuspiciousWorkbook`. */
  rows: ComplianceItem[]
  /** The counts over the whole selection — for the share and the employee cut.
   *  Absent when that query failed; the file is still worth writing. */
  summary?: ComplianceSummary
  /**
   * The per-customer chains — conversations and sales on one axis.
   *
   * ⚠️ WITHOUT IT THE SHEET IS LEFT OUT ENTIRELY and the file comes out with
   * five sheets. An empty "Xronologiya" would show the worst possible
   * conclusion — "there were no conversations" — when in fact the request was
   * simply never made. For the same reason the "Mijozlar" column on
   * "Xodimlar bo'yicha" stays empty without it.
   */
  timeline?: ComplianceTimeline
  /** The period on screen, `YYYY-MM-DD` and WITHOUT a clock (a sale has none).
   *  Both are optional: this panel's date filter can be empty, which means
   *  "everything" — and then the period is taken from the rows. */
  since?: string
  until?: string
  /** A one-line description of the filter on screen. */
  scope?: string
  /** The window calls are searched in. Falls back to the summary's own
   *  `window_days`, which is the same number from the same response. */
  windowDays?: number
  /** Injected so the builder stays pure and its test is not time-dependent. */
  generatedAt?: Date
}

export interface SuspiciousWorkbook {
  fileName: string
  sheets: SuspiciousSheet[]
}

/**
 * `shubhali-savdolar-2026-07-22_2026-08-20.xlsx`, or the day it was downloaded
 * when the selection is empty.
 *
 * The dates being in the name matters: these files pile up in a folder and
 * nobody can tell which period `shubhali-savdolar(3).xlsx` belongs to.
 */
export function fileName(
  rows: ComplianceItem[],
  since: string | undefined,
  until: string | undefined,
  generatedAt: Date,
): string {
  return `${t('sales.exportSuspicious.file')}-${periodStamp(rows, since, until, generatedAt)}.xlsx`
}

/** Rows in, sheets out. **Pure** — no DOM, no library, no clock of its own. */
export function buildSuspiciousWorkbook({
  rows,
  summary,
  timeline,
  since,
  until,
  scope,
  windowDays,
  generatedAt = new Date(),
}: SuspiciousExportOptions): SuspiciousWorkbook {
  /* A guard: a clean row landing in a file headed "Shubhali savdolar" would
     make the report contradict itself. The caller has already set the filter,
     but the condition is checked here too — this module is what answers for
     the file. */
  const suspicious = rows.filter((row) => row.verdict === 'suspicious')

  /* The window, from whichever response carried it. Both state the same
     setting, and an old file has to say which threshold produced it. */
  const days = windowDays ?? summary?.window_days

  const period = periodOf(suspicious, since, until)
  const meta: Meta = {
    period: period
      ? t('sales.export.period', {
          /* ⚠️ NO `T00:00:00` APPENDED. `saleDate.ts` explains it in full: a
             bare `YYYY-MM-DD` parses as UTC midnight, which is the same
             calendar day in Asia/Tashkent whatever the reader's own zone. The
             source appended a clock because it rendered in the browser's zone;
             here that would print the previous day for a reader east of
             UTC+5. */
          from: formatSaleDate(period.from),
          to: formatSaleDate(period.to),
        })
      : '',
    scope: [t('sales.export.rows', { count: suspicious.length }), scope]
      .filter(Boolean)
      .join(' · '),
    generated: t('sales.export.generated', { value: formatDateTime(generatedAt) }),
  }

  const overview = summarySheet(suspicious, summary, meta, days)
  const sales = salesSheet(suspicious, meta)
  const agents = agentsSheet(suspicious, summary, meta, timeline)
  const clients = clientsSheet(suspicious, meta)
  /* An optional sheet: with no request made, the file comes out with five
     sheets as before (the reason is on `SuspiciousExportOptions.timeline`). */
  const chronology = timeline ? timelineSheet(timeline, meta) : null
  const glossary = glossarySheet(meta, days, Boolean(timeline))

  /* ⚠️ THE GRID IS OFF ON EVERY SHEET. A grey grid makes everything in the
     file look like raw data; with it off the only lines the eye sees are the
     ones drawn on purpose and the sheet reads as a document. `landscape` is
     for print: a 22-column table splits across two pages in portrait. */
  const sheets: SuspiciousSheet[] = [
    {
      data: overview.data,
      sheet: t('sales.exportSuspicious.sheetSummary'),
      columns: overview.widths.map((width) => ({ width })),
      showGridLines: false,
    },
    {
      data: sales.data,
      sheet: t('sales.export.sheetSales'),
      columns: sales.widths.map((width) => ({ width })),
      showGridLines: false,
      orientation: 'landscape',
      /* The header block plus the table header. Frozen, so the column names
         stay put while scrolling — without it, twenty columns in, nobody knows
         which figure belongs to which. The first column is frozen too: when
         scrolled right, the row must still say which sale it is. */
      stickyRowsCount: HEAD_ROWS + 1,
      stickyColumnsCount: 1,
    },
    {
      data: agents.data,
      sheet: t('sales.exportSuspicious.sheetAgents'),
      columns: agents.widths.map((width) => ({ width })),
      showGridLines: false,
      stickyRowsCount: HEAD_ROWS + 1,
      stickyColumnsCount: 1,
    },
    {
      data: clients.data,
      sheet: t('sales.exportSuspicious.sheetClients'),
      columns: clients.widths.map((width) => ({ width })),
      showGridLines: false,
      orientation: 'landscape',
      stickyRowsCount: HEAD_ROWS + 1,
      stickyColumnsCount: 1,
    },
    /* The timeline comes AFTER "Mijozlar bo'yicha": the file is read from the
       overall figures towards the detail, and the glossary is always last. */
    ...(chronology
      ? [
          {
            data: chronology.data,
            sheet: t('sales.exportSuspicious.sheetTimeline'),
            columns: chronology.widths.map((width) => ({ width })),
            showGridLines: false,
            orientation: 'landscape' as const,
            /* The warning row pushes the table down by one, so the number
               comes from the SHEET itself. */
            stickyRowsCount: chronology.sticky,
            /* Three columns frozen: employee, customer code and name. Scrolled
               right, the row must still say WHOSE it is — without that an
               11-column axis cannot be read. */
            stickyColumnsCount: 3,
          },
        ]
      : []),
    {
      data: glossary.data,
      sheet: t('sales.exportSuspicious.sheetGlossary'),
      columns: glossary.widths.map((width) => ({ width })),
      showGridLines: false,
    },
  ]

  return { fileName: fileName(suspicious, since, until, generatedAt), sheets }
}

/** Build it and write it. The only part that loads the library. */
export async function exportSuspiciousSales(options: SuspiciousExportOptions): Promise<void> {
  const workbook = buildSuspiciousWorkbook(options)
  const writeXlsxFile = (await import('write-excel-file/browser')).default
  await writeXlsxFile(workbook.sheets).toFile(workbook.fileName)
}
