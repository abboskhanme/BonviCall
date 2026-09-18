/**
 * Sales control as an Excel file — the ARCHIVE.
 *
 * Ported from `../BonviZvonki/services/web/src/modules/sales/export.ts`,
 * comments translated (CONVENTIONS.md §14). Its opening argument is kept
 * because it is the reason the file has 25 columns rather than the screen's 7:
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * WHY THIS EXISTS AT ALL. It is not a convenience — it is the contract's
 * §4: "the manager wants to re-count the figure by hand". So every EVIDENCE
 * column is in the file: when the last conversation was and with whom, how
 * many days before the sale, the previous sale, the conversations between the
 * two and in the whole history, the customer's code and phone. Without them
 * the file cannot be checked against SAP, which is the only thing it is for.
 *
 * ⚠️ THE WHOLE SELECTION, NOT THE PAGE ON SCREEN. The table shows 50 rows; the
 * file gets every row the filter holds (`fetchAll.ts`). A one-page file would
 * state "12 suspicious sales" for a filter holding 451 — a false conclusion in
 * a document that gets emailed onward.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ── SHEETS ────────────────────────────────────────────────────
 *   1. "Savdolar"  the evidence table, one sale per row.
 *   2. "Yig'ma"    the three class counts and the per-employee cut.
 *
 * Two sheets and no glossary: this file is the archive, and its two section
 * reports (`exportSuspicious.ts`, `exportOverLimit.ts`) are the ones a person
 * READS — they carry the definitions. Here the columns are the screen's own,
 * under the headings the screen uses.
 *
 * The library is imported DYNAMICALLY — it is needed only when the button is
 * pressed, and a static import would ship it to every reader of the page.
 *
 * ── TESTING ───────────────────────────────────────────────────
 * `buildComplianceWorkbook` is pure: rows in, sheet descriptors out. No DOM,
 * no library, and the clock is injected — so the layout and the arithmetic are
 * testable in Node. `exportCompliance` is the thin shell that writes the file.
 */
import type { CellObject, Row, Sheet, SheetData } from 'write-excel-file/browser'

import { t } from '@/shared/i18n'
import { formatDateTime, zonedParts } from '@/shared/lib/format'
import {
  BAD,
  GOOD,
  HEADER,
  META,
  MUTED,
  RULE,
  TITLE,
  TOTAL,
  WARN,
  type CellStyle,
  date,
  datetime,
  money,
  num,
  span,
  text,
} from '@/shared/lib/xlsx'

import {
  REASON_LABEL,
  REVIEW_LABEL,
  SKIP_LABEL,
  VERDICTS,
  VERDICT_LABEL,
  type AgentBreakdown,
  type ComplianceItem,
  type ComplianceSummary,
  type Verdict,
} from './api'
import { MAX_ROWS } from './fetchAll'
import { formatSaleDate } from './saleDate'

/** A sheet as this module builds it — the library's own type, minus images. */
export type SalesSheet = Omit<Sheet<Blob>, 'images'>

/** The class colours, the same three the badges use on screen. */
const VERDICT_COLOR: Record<Verdict, string | undefined> = {
  ok: GOOD,
  suspicious: WARN,
  not_checkable: MUTED,
}

/* ── The columns ──────────────────────────────────────────── */

interface Column {
  header: string
  width: number
  /** The header's own alignment — a numeric column's heading sits over its
   *  figures, not over the column's left edge. */
  align?: CellStyle['align']
  cell: (row: ComplianceItem, base: CellStyle) => CellObject
}

function columns(windowDays: number | undefined): Column[] {
  return [
    {
      header: t('sales.col.date'),
      width: 12,
      align: 'center',
      cell: (row, base) => date(row.occurred_on, { align: 'center', ...base }),
    },
    {
      /* SAP's `Номер операции`. The whole point of the file is here: this is
         the number the manager finds the row in SAP by. */
      header: t('sales.col.operation'),
      width: 13,
      cell: (row, base) => text(row.external_id, { textColor: MUTED, ...base }),
    },
    {
      /* ⚠️ ADDED IN THE PORT. SAP's `Номер документа` is the piece of PAPER,
         and it is not interchangeable with the operation number — the card on
         screen shows both for the same reason. */
      header: t('sales.col.document'),
      width: 13,
      cell: (row, base) => text(row.doc_number, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.client'),
      width: 32,
      cell: (row, base) => text(row.partner_name, base),
    },
    {
      header: t('sales.col.code'),
      width: 11,
      cell: (row, base) => text(row.partner_code, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.phone'),
      width: 16,
      /* As SAP wrote it, deliberately unformatted: this column is compared
         against SAP's own cell, and a prettified number no longer matches. */
      cell: (row, base) => text(row.phone, base),
    },
    {
      /* ⚠️ TWO COLUMNS FOR ONE PERSON, unlike the screen. `seller.ts` shows a
         single name because a row has no space for two; a file being checked
         against SAP needs both — SAP's own wording to find the row there, and
         the employee card to reconcile with the per-employee sheet. */
      header: t('sales.col.branch'),
      width: 22,
      cell: (row, base) => text(row.branch, base),
    },
    {
      header: t('sales.col.agent'),
      width: 20,
      /* A sale with no employee is written out, never left blank: some
         branches are DELIBERATELY unlinked, and an empty cell would read as a
         fault. */
      cell: (row, base) =>
        row.agent_name
          ? text(row.agent_name, base)
          : text(t('sales.noAgent'), { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.direction'),
      width: 12,
      cell: (row, base) => text(row.direction, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.amountUsd'),
      width: 14,
      align: 'right',
      cell: (row, base) => money(row.amount_usd, { fontWeight: 'bold', ...base }),
    },
    {
      header: t('sales.col.amount'),
      width: 16,
      align: 'right',
      cell: (row, base) => money(row.amount, base),
    },
    {
      header: t('sales.col.currency'),
      width: 9,
      align: 'center',
      cell: (row, base) => text(row.currency, { align: 'center', ...base }),
    },
    {
      header: t('sales.col.verdict'),
      width: 18,
      cell: (row, base) =>
        text(t(VERDICT_LABEL[row.verdict]), {
          textColor: VERDICT_COLOR[row.verdict],
          fontWeight: 'bold',
          ...base,
        }),
    },
    {
      header: t('sales.col.skipReason'),
      width: 26,
      /* `skip_reason` is a plain string on the wire, so the lookup may MISS —
         an unknown code leaves the cell empty rather than printing a dotted
         identifier into a spreadsheet. */
      cell: (row, base) => {
        const key = row.skip_reason ? SKIP_LABEL[row.skip_reason] : undefined
        return text(key ? t(key) : null, { textColor: MUTED, ...base })
      },
    },
    {
      header: t('sales.col.rules'),
      width: 14,
      align: 'center',
      /* The CODES, joined — `R1, R3`. The sentence behind each one is on the
         section reports' glossary sheet; here the column has to stay narrow
         enough to sit beside the evidence it summarises. */
      cell: (row, base) =>
        text(row.broken_rules.join(', ') || null, {
          textColor: row.broken_rules.length ? WARN : undefined,
          align: 'center',
          ...base,
        }),
    },
    {
      /* The window travels in the file too: the setting can be changed later,
         and an old file then still states the threshold it was built with. */
      header: t('sales.col.window'),
      width: 10,
      align: 'center',
      cell: (_row, base) => num(windowDays ?? null, { align: 'center', ...base }),
    },
    {
      header: t('sales.col.lastCall'),
      width: 18,
      /* "Never" is written out, in the bad tone. An empty cell here would be
         read as "we failed to look", which is the opposite of what it means. */
      cell: (row, base) =>
        row.last_call_at
          ? datetime(row.last_call_at, base)
          : text(t('sales.noCallEver'), { textColor: BAD, ...base }),
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
      cell: (row, base) => num(row.days_before, { align: 'center', ...base }),
    },
    {
      header: t('sales.col.previousSale'),
      width: 13,
      align: 'center',
      cell: (row, base) => date(row.previous_sale_on, { align: 'center', ...base }),
    },
    {
      header: t('sales.col.callsBetween'),
      width: 14,
      align: 'center',
      cell: (row, base) =>
        num(row.calls_between, {
          align: 'center',
          textColor: row.calls_between === 0 ? WARN : undefined,
          ...base,
        }),
    },
    {
      header: t('sales.col.callsTotal'),
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
      header: t('sales.col.decision'),
      width: 18,
      /* An undecided sale says "Ko'rilmagan" rather than nothing: this is the
         review QUEUE, and a blank decision column would read as an archive
         nobody ever worked through. */
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
      header: t('sales.col.decisionReason'),
      width: 18,
      cell: (row, base) =>
        text(row.review?.reason ? t(REASON_LABEL[row.review.reason]) : null, base),
    },
    {
      header: t('sales.col.note'),
      width: 34,
      cell: (row, base) => text(row.review?.note, { wrap: true, ...base }),
    },
    {
      header: t('sales.col.reviewedBy'),
      width: 20,
      cell: (row, base) => text(row.review?.reviewed_by, { textColor: MUTED, ...base }),
    },
    {
      header: t('sales.col.reviewedAt'),
      width: 18,
      cell: (row, base) => datetime(row.review?.reviewed_at, { textColor: MUTED, ...base }),
    },
  ]
}

/* ── The header block ─────────────────────────────────────── */

interface Meta {
  period: string
  scope: string
  generated: string
  /** Present only when the row cap cut the selection. */
  truncated?: string
}

/**
 * The sales sheet: a title block, then the table.
 *
 * The block carries the period, the filter and when it was downloaded, because
 * a file loses its context the moment it is emailed — and in THIS report that
 * is dangerous: "45 suspicious sales" with no period beside it reads as a
 * statement about the whole year.
 */
function salesSheet(
  rows: ComplianceItem[],
  meta: Meta,
  windowDays: number | undefined,
): { data: SheetData; widths: number[]; headerRows: number } {
  const cols = columns(windowDays)
  const width = cols.length

  const title = (value: string, style: CellStyle): Row => span(text(value, style), width)

  const data: SheetData = [
    title(t('sales.title'), TITLE),
    /* ⚠️ THE WARNING IS IN THE FILE ITSELF. On screen it sits under the
       heading; the file travels on its own, and without the sentence it reads
       as a list of accusations. */
    title(t('sales.subtitle'), { fontSize: 10, textColor: WARN, wrap: true }),
  ]
  /* An empty selection has no period at all; a blank line in its place would
     read as a heading that failed to render. */
  if (meta.period) data.push(title(meta.period, { ...META, fontSize: 11 }))
  data.push(title(meta.scope, META))
  data.push(title(meta.generated, META))
  if (meta.truncated) data.push(title(meta.truncated, { fontSize: 10, textColor: BAD, wrap: true }))
  data.push([])
  data.push(cols.map((column) => text(column.header, { ...HEADER, align: column.align })))

  rows.forEach((row) => {
    /* No zebra — a hairline under each row instead (`shared/lib/xlsx.ts`). */
    data.push(cols.map((column) => column.cell(row, RULE)))
  })

  return { data, widths: cols.map((column) => column.width), headerRows: data.length - rows.length }
}

/* ── The summary sheet ────────────────────────────────────── */

/**
 * The three class counts and the per-employee cut.
 *
 * ALL THREE classes are written, `not_checkable` included. Dropping it would
 * make the file contradict the screen and would lose the one number that
 * measures SAP's own data quality.
 */
function summarySheet(summary: ComplianceSummary): { data: SheetData; widths: number[] } {
  const data: SheetData = [
    span(text(t('sales.exportSuspicious.sheetSummary'), TITLE), 2),
    [],
    ...VERDICTS.map((verdict): Row => [
      text(t(VERDICT_LABEL[verdict]), RULE),
      num(summary[verdict], {
        fontWeight: 'bold',
        textColor: VERDICT_COLOR[verdict],
        ...RULE,
      }),
    ]),
    [text(t('sales.export.totalRow'), TOTAL), num(summary.total, TOTAL)],
  ]

  /* The per-employee cut answers "who has the most unjustified sales", and
     carries `not_checkable` beside it: where that column is high the problem
     is the branch's data in SAP, not the employee. */
  if (summary.agents.length) {
    data.push([], [])
    data.push(
      [
        t('sales.col.agent'),
        t('sales.col.sales'),
        t('sales.verdict.ok'),
        t('sales.verdict.suspicious'),
        t('sales.verdict.not_checkable'),
        t('sales.review.new'),
        t('sales.review.justified'),
        t('sales.review.confirmed'),
      ].map((header, index) => text(header, { ...HEADER, align: index ? 'right' : undefined })),
    )
    summary.agents.forEach((agent: AgentBreakdown) => {
      data.push([
        text(agent.agent_name ?? t('sales.noAgent'), {
          ...RULE,
          textColor: agent.agent_name ? undefined : MUTED,
        }),
        num(agent.sales, RULE),
        num(agent.ok, { textColor: GOOD, ...RULE }),
        num(agent.suspicious, { textColor: agent.suspicious ? WARN : undefined, ...RULE }),
        num(agent.not_checkable, { textColor: MUTED, ...RULE }),
        num(agent.new, RULE),
        num(agent.justified, { textColor: GOOD, ...RULE }),
        num(agent.confirmed, { textColor: agent.confirmed ? BAD : undefined, ...RULE }),
      ])
    })
  }

  return { data, widths: [30, 14, 12, 16, 18, 16, 14, 22] }
}

/* ── Entry point ──────────────────────────────────────────── */

export interface ComplianceExportOptions {
  rows: ComplianceItem[]
  /** Absent when the count query failed — the file is still worth writing. */
  summary?: ComplianceSummary
  /** The period on screen, `YYYY-MM-DD`. Both are optional: this panel's date
   *  filter can be empty, which means "everything". */
  since?: string
  until?: string
  /** A one-line description of the filter, assembled by the page. */
  scope?: string
  windowDays?: number
  /** The row cap cut the selection (`fetchAll.ts`). */
  truncated?: boolean
  /** Injected so the builder stays pure and its test is not time-dependent. */
  generatedAt?: Date
}

/**
 * The period the file covers, in the file's own words.
 *
 * With no date filter on screen the bounds are taken from the ROWS, so the
 * heading still says which days are in the file. An empty selection has no
 * period at all, and the line is dropped rather than printed as `— — —`.
 *
 * Exported because the two SECTION reports take their period as two required
 * strings, and this panel's date filter — unlike the source's — may be empty.
 * One rule for what "the period of this file" means, in one place.
 */
export function periodOf(
  rows: ComplianceItem[],
  since: string | undefined,
  until: string | undefined,
): { from: string; to: string } | null {
  const days = rows.map((row) => row.occurred_on).sort()
  const from = since ?? days[0]
  const to = until ?? days[days.length - 1]
  if (!from || !to) return null
  return { from, to }
}

/**
 * The period part of a file's name — `2026-07-22_2026-08-20`, or the day of
 * the download when the selection is empty.
 *
 * Shared by all three sales exports: these files pile up in one folder, and
 * the period in the name is the only way to tell them apart. One copy, so
 * three reports cannot name their periods three different ways.
 *
 * ⚠️ The fallback day is TASHKENT's, not the browser's. A manager exporting at
 * 01:30 Tashkent would otherwise get yesterday's date in the name while every
 * date inside the file is today's.
 */
export function periodStamp(
  rows: ComplianceItem[],
  since: string | undefined,
  until: string | undefined,
  generatedAt: Date,
): string {
  const period = periodOf(rows, since, until)
  if (period) return `${period.from}_${period.to}`
  const today = zonedParts(generatedAt, { year: 'numeric', month: '2-digit', day: '2-digit' })
  return `${today.year}-${today.month}-${today.day}`
}

/** `savdo-nazorati-2026-07-22_2026-08-20.xlsx`. */
export function fileName(
  rows: ComplianceItem[],
  since: string | undefined,
  until: string | undefined,
  generatedAt: Date,
): string {
  return `${t('sales.export.file')}-${periodStamp(rows, since, until, generatedAt)}.xlsx`
}

export interface ComplianceWorkbook {
  fileName: string
  sheets: SalesSheet[]
}

/** Rows in, sheets out. **Pure** — no DOM, no library, no clock of its own. */
export function buildComplianceWorkbook({
  rows,
  summary,
  since,
  until,
  scope,
  windowDays,
  truncated = false,
  generatedAt = new Date(),
}: ComplianceExportOptions): ComplianceWorkbook {
  const period = periodOf(rows, since, until)
  const meta: Meta = {
    period: period
      ? t('sales.export.period', {
          from: formatSaleDate(period.from),
          to: formatSaleDate(period.to),
        })
      : '',
    scope: [t('sales.export.rows', { count: rows.length }), scope].filter(Boolean).join(' · '),
    generated: t('sales.export.generated', { value: formatDateTime(generatedAt) }),
    ...(truncated ? { truncated: t('sales.export.truncated', { count: MAX_ROWS }) } : {}),
  }

  const sales = salesSheet(rows, meta, windowDays)
  const sheets: SalesSheet[] = [
    {
      data: sales.data,
      sheet: t('sales.export.sheetSales'),
      columns: sales.widths.map((width) => ({ width })),
      /* The grid is off on every sheet: with it on the file looks like raw
         data, and the only lines the eye should see are the ones drawn on
         purpose. Landscape because 25 columns split across two pages in
         portrait. */
      showGridLines: false,
      orientation: 'landscape',
      /* The title block plus the blank line plus the header row. Frozen, or
         twenty columns in nobody knows which number belongs to which; the
         first column is frozen too so the sale's date stays visible. */
      stickyRowsCount: sales.headerRows,
      stickyColumnsCount: 1,
    },
  ]

  if (summary) {
    const totals = summarySheet(summary)
    sheets.push({
      data: totals.data,
      sheet: t('sales.export.sheetSummary'),
      columns: totals.widths.map((width) => ({ width })),
      showGridLines: false,
      stickyRowsCount: 1,
      stickyColumnsCount: 1,
    })
  }

  return { fileName: fileName(rows, since, until, generatedAt), sheets }
}

/** Build it and write it. The only part that loads the library. */
export async function exportCompliance(options: ComplianceExportOptions): Promise<void> {
  const workbook = buildComplianceWorkbook(options)
  const writeXlsxFile = (await import('write-excel-file/browser')).default
  await writeXlsxFile(workbook.sheets).toFile(workbook.fileName)
}
