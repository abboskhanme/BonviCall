/**
 * The activity report as an Excel file — built IN THE BROWSER, on purpose.
 *
 * Ported from BonviZvonki `web/src/modules/activity/export.ts`, comments
 * translated (CONVENTIONS.md §14). Its opening argument is the reason this is
 * not a server endpoint and is kept word for word:
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * WHY IN THE BROWSER AND NOT ON THE SERVER. The file must carry EXACTLY what
 * is on screen — the same filter, the same numbers. They are already here: the
 * page is rendering the `useActivity` response. Computing them a second time
 * on the server would create two truths, and they drift: a filter is added on
 * one side, a rounding rule changes on the other, and the manager asks why the
 * figure in the file differs from the figure on screen. The labels come out in
 * the reader's own language too; the server only knows one.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * (In BonviCall the second half of that argument is weaker — there is one
 * language — and the first half is stronger: the page can also be SORTED, and
 * the file is written from the rows in the order the reader put them in.)
 *
 * ── SHEETS ────────────────────────────────────────────────────
 *
 *   1. "Xulosa"            the sheet somebody is shown: four headline figures
 *                          and the trend CHART.
 *   2. "Xodimlar bo'yicha" the working table (sort it, filter it).
 *   3. "Kunlar/Soatlar"    the chart's own numbers.
 *   4. "Izohlar"           the terms and how each one is computed.
 *
 * Why split: a title block, four KPIs and a thirteen-column table on one sheet
 * make both unreadable — the table is pushed down out of sight and the KPIs
 * read as part of it. Each sheet does one job.
 *
 * ⚠️ THE CHART IS A PICTURE, not an Excel chart. Excel's own chart cannot
 * reproduce what is on screen (the smoothed curve, the area gradient, the
 * colours), so the file would look like a different report. A picture looks the
 * same everywhere and prints. Its numbers are not lost: the whole table behind
 * it is sheet 3.
 *
 * The library is imported DYNAMICALLY — it is only needed when the button is
 * pressed. A static import would ship it to every reader of the page, including
 * everyone who never exports anything.
 *
 * ── TESTING ───────────────────────────────────────────────────
 * `buildWorkbook` is a pure function: report in, sheet descriptors out. It
 * touches no DOM, no canvas and no library, so the arithmetic and the layout
 * are testable without a browser. `exportActivity` is the thin shell that adds
 * the picture and writes the file.
 */
import type { CellObject, Row, Sheet, SheetData } from 'write-excel-file/browser'

import { isoDateLabel } from '@/modules/dashboard/chart'
import { formatDateTime } from '@/shared/lib/format'

import type { ActivityDay, ActivityHour, ActivityReport, ActivityRow } from './api'
import { renderChartImage, type ChartImage } from './chartImage'
import { t } from '@/shared/i18n'
import {
  SERIES,
  TONE_HEX,
  medianTone,
  rateTone,
  type SeriesKey,
} from './series'

/* ── Cells ────────────────────────────────────────────────────
   Only the library's TYPES are imported. A type import is erased at build time,
   so this file does not pull the library in until `exportActivity` asks for it
   — which is the whole point of the dynamic import below. */
type CellStyle = Omit<CellObject, 'value' | 'type'>

/** One row of a sheet. Re-exported so a test can name it without importing the
 *  library, which is the one thing this module is careful not to load early. */
export type SheetRow = Row

/* ── Colours ──────────────────────────────────────────────────
   The light-theme tokens of `src/index.css`. Excel has no theme, so the file
   uses the light values and reads as a continuation of the screen: a red
   number is the same red in both. */
const NAVY = '#215A8C' // --accent
const BAD = '#CC1E36' // --bad
const INK = '#151D28' // --text
const MUTED = '#677383' // --muted
/** The rule between rows — NOT a zebra.
 *
 *  Alternating grey and white over thirteen columns tires the eye and makes
 *  the file look machine-generated. A hairline does the same job — the eye
 *  does not lose the row — and the sheet stays white and quiet. */
const RULE_COLOR = '#E3E7ED' // --border
const BAND = '#F4F6F9' // --surface-2

/** Thousands separated. */
const NUM = '#,##0'
/** Percent: the wire carries 0-100, Excel expects a fraction. */
const PCT = '0.0%'
/** Minutes, one decimal — as on screen. */
const MIN = '0.0'
/**
 * Talk time as a REAL duration (`6:59:00`), not text.
 *
 * ⚠️ `[h]` in square brackets: a plain `h` wraps at 24 hours, so "31 hours 12
 * minutes" would display as "7:12". On the total row that happens nearly every
 * time.
 */
const DUR = '[h]:mm:ss'

/** Excel counts a day as 1, so seconds are converted into that unit. */
const DAY_SECONDS = 86_400

function text(value: string, style: CellStyle = {}): CellObject {
  return { value, type: String, ...style }
}

function num(value: number | null | undefined, style: CellStyle = {}): CellObject {
  if (value === null || value === undefined) return { ...style }
  return { value, type: Number, format: NUM, ...style }
}

/** A percentage cell. `null` leaves it empty — the screen shows an em dash. */
function pct(value: number | null, style: CellStyle = {}): CellObject {
  if (value === null) return { ...style }
  return { value: value / 100, type: Number, format: PCT, ...style }
}

function minutes(value: number | null, style: CellStyle = {}): CellObject {
  if (value === null) return { ...style }
  return { value, type: Number, format: MIN, ...style }
}

function duration(seconds: number, style: CellStyle = {}): CellObject {
  return { value: seconds / DAY_SECONDS, type: Number, format: DUR, ...style }
}

/* ── Styles ───────────────────────────────────────────────── */

const TITLE: CellStyle = { fontWeight: 'bold', fontSize: 15, textColor: INK }
const META: CellStyle = { fontSize: 10, textColor: MUTED }
/** A section heading — small, bold, ruled underneath. Unlike a large coloured
 *  title it divides the sheet without demanding attention. */
const SECTION: CellStyle = {
  fontWeight: 'bold',
  fontSize: 9,
  textColor: MUTED,
  bottomBorderStyle: 'thin',
  bottomBorderColor: RULE_COLOR,
}

const HEADER: CellStyle = {
  fontWeight: 'bold',
  fontSize: 10,
  textColor: '#FFFFFF',
  backgroundColor: NAVY,
  alignVertical: 'center',
  wrap: true,
  height: 34,
}

/** The hairline under every data cell. */
const RULE: CellStyle = { bottomBorderStyle: 'thin', bottomBorderColor: RULE_COLOR }

const TOTAL: CellStyle = {
  fontWeight: 'bold',
  backgroundColor: BAND,
  topBorderStyle: 'medium',
  topBorderColor: NAVY,
}

/* ── Columns ──────────────────────────────────────────────── */

interface Column {
  header: string
  width: number
  /** Where the HEADER aligns. Excel right-aligns numbers and left-aligns text
   *  by default, so a numeric column with a left-aligned header looks crooked. */
  align?: 'left' | 'right'
  cell: (row: ActivityRow, base: CellStyle) => CellObject
}

/**
 * The table's columns, in the screen's order.
 *
 * Two columns the screen does not have are here deliberately — the "answered"
 * counts. They appear in the cards above the table and arrive in the same
 * response, so they are not a new calculation; the file has room and not having
 * to reopen the report is worth something.
 */
function columns(): Column[] {
  return [
    {
      header: t('activity.colAgent'),
      width: 28,
      cell: (row, base) => text(row.agent_name, base),
    },
    {
      header: t('activity.colOut'),
      width: 12,
      align: 'right',
      cell: (row, base) => num(row.outbound_total, base),
    },
    {
      header: t('activity.export.outAnswered'),
      width: 14,
      align: 'right',
      cell: (row, base) => num(row.outbound_answered, { textColor: MUTED, ...base }),
    },
    {
      header: t('activity.colOutNoAnswer'),
      width: 16,
      align: 'right',
      cell: (row, base) => num(row.outbound_no_answer, base),
    },
    {
      header: t('activity.colIn'),
      width: 12,
      align: 'right',
      cell: (row, base) => num(row.inbound_total, base),
    },
    {
      header: t('activity.export.inAnswered'),
      width: 14,
      align: 'right',
      cell: (row, base) => num(row.inbound_answered, { textColor: MUTED, ...base }),
    },
    {
      header: t('activity.colMissed'),
      width: 16,
      align: 'right',
      /* Red only above zero. A red zero would be a false signal that something
         is wrong here. */
      cell: (row, base) =>
        num(row.missed, { textColor: row.missed ? BAD : undefined, ...base }),
    },
    {
      header: t('activity.export.missedRate'),
      width: 12,
      align: 'right',
      cell: (row, base) => pct(row.missed_rate, base),
    },
    {
      header: t('activity.colClients'),
      width: 11,
      align: 'right',
      cell: (row, base) => num(row.missed_clients, base),
    },
    {
      header: t('activity.colUnreached'),
      width: 14,
      align: 'right',
      cell: (row, base) =>
        num(row.clients_unreached, {
          textColor: row.clients_unreached ? BAD : undefined,
          fontWeight: row.clients_unreached ? 'bold' : undefined,
          ...base,
        }),
    },
    {
      header: t('activity.colRate'),
      width: 12,
      align: 'right',
      cell: (row, base) =>
        pct(row.callback_rate, {
          textColor: TONE_HEX[rateTone(row.callback_rate)],
          fontWeight: 'bold',
          ...base,
        }),
    },
    {
      header: t('activity.export.median'),
      width: 15,
      align: 'right',
      cell: (row, base) =>
        minutes(row.callback_median_minutes, {
          textColor: TONE_HEX[medianTone(row.callback_median_minutes)],
          ...base,
        }),
    },
    {
      header: t('activity.colTalk'),
      width: 13,
      align: 'right',
      /* A real duration, not a string: Excel can sort and sum it. "6 soat 59
         daq" allows neither. */
      cell: (row, base) => duration(row.talk_seconds, base),
    },
  ]
}

/** One cell spread across several columns — for titles and notes. */
function span(cell: CellObject, width: number): SheetRow {
  return [{ ...cell, columnSpan: width }, ...Array.from({ length: width - 1 }, () => null)]
}

/**
 * A long note in a merged cell, with its HEIGHT worked out.
 *
 * ⚠️ Excel does not auto-size the row height of a MERGED cell (it does for an
 * ordinary one). Without a height only the first line of a multi-line note
 * shows and the rest stays inside the cell — which means the report's most
 * important explanations are the ones nobody reads.
 */
function note(value: string, style: CellStyle, width: number, perLine: number): SheetRow {
  const lines = Math.max(1, Math.ceil(value.length / perLine))
  return span(text(value, { ...style, wrap: true, height: lines * 15 + 3 }), width)
}

/* ── Sheet 1: the summary ─────────────────────────────────── */

/** How many columns the summary sheet has; notes span all of them. */
const SUMMARY_SPAN = 6
/** Their combined width in characters, for the note-height arithmetic. A
 *  little under the sum of `widths` below: a word that wraps whole leaves the
 *  line short. */
const SUMMARY_LINE = 112

export interface Meta {
  period: string
  scope: string
  generated: string
}

/**
 * Title → four figures → the chart.
 *
 * The figures are EXACTLY the cards on screen — same label, same sub-line: the
 * file has to look familiar the moment it opens, or the reader wonders whether
 * it is a different report.
 *
 * No merged "card" boxes. A merged cell breaks both sorting and copying in
 * Excel, and files built that way are exactly the ones that look
 * machine-generated. Label in the left column, number beside it, note to the
 * right: plain, and readable.
 */
export function summarySheet(
  report: ActivityReport,
  meta: Meta,
): { data: SheetData; widths: number[]; chartRow: number } {
  const total = report.total
  const data: SheetData = [
    span(text(t('activity.title'), TITLE), SUMMARY_SPAN),
    span(text(meta.period, META), SUMMARY_SPAN),
    span(text(`${meta.scope} · ${meta.generated}`, META), SUMMARY_SPAN),
    [],
    span(text(t('activity.export.metrics'), SECTION), SUMMARY_SPAN),
  ]

  /** One figure: label · number · note. */
  const metric = (label: string, value: CellObject, hint: string | undefined): SheetRow => [
    text(label, { fontSize: 11, textColor: INK }),
    { ...value, fontWeight: 'bold', fontSize: 14 },
    ...(hint ? span(text(hint, { fontSize: 10, textColor: MUTED }), SUMMARY_SPAN - 2) : []),
  ]

  data.push(
    metric(
      t('activity.outbound'),
      num(total.outbound_total, { textColor: NAVY }),
      t('activity.answeredOf', {
        count: total.outbound_answered,
        total: total.outbound_total,
      }),
    ),
    metric(
      t('activity.inbound'),
      num(total.inbound_total, { textColor: NAVY }),
      t('activity.answeredOf', {
        count: total.inbound_answered,
        total: total.inbound_total,
      }),
    ),
    metric(
      t('activity.missed'),
      num(total.missed, { textColor: total.missed ? BAD : INK }),
      total.missed_rate !== null
        ? t('activity.ofInbound', { percent: total.missed_rate })
        : undefined,
    ),
    metric(
      t('activity.unreached'),
      num(total.clients_unreached, {
        textColor: total.clients_unreached ? BAD : TONE_HEX.good,
      }),
      total.callback_rate !== null
        ? t('activity.unreachedSub', {
            reached: total.clients_reached,
            clients: total.missed_clients,
            percent: total.callback_rate,
          })
        : undefined,
    ),
  )

  /* The median: small, and the figure most often asked about in a
     presentation — "how long do they take to call back?" */
  if (report.callback_median_minutes !== null) {
    data.push(
      [],
      note(
        t('activity.medianNote', {
          minutes: report.callback_median_minutes,
          hours: report.callback_window_hours,
        }),
        { fontSize: 10, textColor: MUTED },
        SUMMARY_SPAN,
        SUMMARY_LINE,
      ),
    )
  }

  data.push([])

  return {
    data,
    widths: [30, 14, 20, 20, 20, 20],
    /* The picture floats ABOVE the cells, so the rows under it must be empty. */
    chartRow: data.length + 1,
  }
}

/* ── Sheet 2: the table ───────────────────────────────────── */

export function agentsSheet(
  report: ActivityReport,
  meta: Meta,
): { data: SheetData; widths: number[] } {
  const cols = columns()
  const width = cols.length

  const data: SheetData = [
    span(text(t('activity.byAgent'), { fontWeight: 'bold', fontSize: 12, textColor: INK }), width),
    span(text(`${meta.period} · ${meta.scope}`, META), width),
    [],
    cols.map((column) => text(column.header, { ...HEADER, align: column.align ?? 'left' })),
  ]

  for (const row of report.agents) {
    data.push(cols.map((column) => column.cell(row, RULE)))
  }

  /* "Total" sits INSIDE the table, as its last row. On a separate sheet it
     would mean switching sheets to compare against it. */
  if (report.agents.length > 1) {
    const total = report.total
    data.push([
      text(t('activity.totalRow'), TOTAL),
      num(total.outbound_total, TOTAL),
      num(total.outbound_answered, TOTAL),
      num(total.outbound_no_answer, TOTAL),
      num(total.inbound_total, TOTAL),
      num(total.inbound_answered, TOTAL),
      num(total.missed, { ...TOTAL, textColor: total.missed ? BAD : undefined }),
      pct(total.missed_rate, TOTAL),
      num(total.missed_clients, TOTAL),
      num(total.clients_unreached, {
        ...TOTAL,
        textColor: total.clients_unreached ? BAD : undefined,
      }),
      pct(total.callback_rate, {
        ...TOTAL,
        textColor: TONE_HEX[rateTone(total.callback_rate)],
      }),
      /* ⚠️ NOT the average of the employees' medians — the report's own
         median. Medians cannot be averaged, and this is the value on screen. */
      minutes(report.callback_median_minutes, {
        ...TOTAL,
        textColor: TONE_HEX[medianTone(report.callback_median_minutes)],
      }),
      duration(total.talk_seconds, TOTAL),
    ])
  }

  return { data, widths: cols.map((column) => column.width) }
}

/* ── Sheet 3: the chart's numbers ─────────────────────────── */

/**
 * The bars themselves.
 *
 * The cut matches the screen: hours for a one-day window, days for anything
 * longer. Whatever the chart showed is what the file has to contain.
 */
export function seriesSheet(
  report: ActivityReport,
  byHour: boolean,
): { data: SheetData; widths: number[] } {
  const headers = [
    byHour ? t('activity.export.hour') : t('activity.export.day'),
    t('activity.colIn'),
    t('activity.export.inAnswered'),
    t('activity.colMissed'),
    t('activity.colOut'),
    t('activity.colOutNoAnswer'),
    ...(byHour ? [t('activity.export.missedRate')] : []),
  ]

  const data: SheetData = [
    span(
      text(byHour ? t('activity.chartTitleHour') : t('activity.chartTitle'), {
        fontWeight: 'bold',
        fontSize: 12,
        textColor: INK,
      }),
      headers.length,
    ),
    [],
    headers.map((value, index) => text(value, { ...HEADER, align: index ? 'right' : 'left' })),
  ]

  /* ⚠️ THE UNION IS SPELLED OUT. `byHour ? a : b` types as
     `ActivityHour[] | ActivityDay[]`, and TypeScript refuses `forEach` on a
     union of array types. */
  const rows: (ActivityDay | ActivityHour)[] = byHour
    ? report.hours_series
    : report.days_series

  for (const row of rows) {
    const first: CellObject =
      'hour' in row
        ? text(`${String(row.hour).padStart(2, '0')}:00`, { align: 'left', ...RULE })
        : {
            /* ⚠️ `new Date('2026-08-20')` is UTC midnight, and that is exactly
               what is wanted: the library converts the date through
               `getTime()` into Excel's own day number. Given local midnight
               (Tashkent is UTC+5) the file would show the previous day. */
            value: new Date(row.day),
            type: Date,
            format: 'dd.mm.yyyy',
            align: 'left',
            ...RULE,
          }

    data.push([
      first,
      num(row.inbound, RULE),
      num(row.inbound_answered, { textColor: MUTED, ...RULE }),
      num(row.missed, { textColor: row.missed ? BAD : undefined, ...RULE }),
      num(row.outbound, RULE),
      num(row.outbound_no_answer, RULE),
      ...('hour' in row ? [pct(row.missed_rate, RULE)] : []),
    ])
  }

  if (rows.length > 1) {
    const sum = (pick: (row: ActivityDay | ActivityHour) => number) =>
      rows.reduce((acc, row) => acc + pick(row), 0)
    data.push([
      text(t('activity.totalRow'), TOTAL),
      num(sum((row) => row.inbound), TOTAL),
      num(sum((row) => row.inbound_answered), TOTAL),
      num(sum((row) => row.missed), TOTAL),
      num(sum((row) => row.outbound), TOTAL),
      num(sum((row) => row.outbound_no_answer), TOTAL),
      ...(byHour ? [{ ...TOTAL }] : []),
    ])
  }

  return {
    data,
    widths: [14, ...Array.from({ length: headers.length - 1 }, () => 15)],
  }
}

/* ── Sheet 4: the glossary ────────────────────────────────── */

/**
 * The terms sheet.
 *
 * WHY IT EXISTS. On screen every column carries an explanation (it appears
 * when the header is hovered or pressed); in the file it did not — and these
 * are exactly the two columns everybody confuses: "Xodim ko'tarmadi" is our
 * responsibility, "Mijoz ko'tarmadi" is not. The file travels by email and
 * whoever opens it may never have seen the screen.
 *
 * The text is the SAME text the screen shows — written once, or the two
 * eventually contradict each other.
 */
export function glossarySheet(hours: number): { data: SheetData; widths: number[] } {
  const terms: [string, string][] = [
    [t('activity.colOut'), t('activity.tipOut')],
    [t('activity.export.outAnswered'), t('activity.export.outAnsweredTip')],
    [t('activity.colOutNoAnswer'), t('activity.tipOutNoAnswer')],
    [t('activity.colIn'), t('activity.tipIn')],
    [t('activity.export.inAnswered'), t('activity.export.inAnsweredTip')],
    [t('activity.colMissed'), t('activity.tipMissed')],
    [t('activity.export.missedRate'), t('activity.export.missedRateTip')],
    [t('activity.colClients'), t('activity.tipClients')],
    [t('activity.colUnreached'), t('activity.tipUnreached', { hours })],
    [t('activity.colRate'), t('activity.tipRate')],
    [t('activity.export.median'), t('activity.tipMedian')],
    [t('activity.colTalk'), t('activity.tipTalk')],
  ]

  const data: SheetData = [
    span(
      text(t('activity.export.sheetGlossary'), {
        fontWeight: 'bold',
        fontSize: 12,
        textColor: INK,
      }),
      2,
    ),
    [],
    [
      text(t('activity.export.term'), { ...HEADER, height: 24, wrap: false }),
      text(t('activity.export.definition'), { ...HEADER, height: 24, wrap: false }),
    ],
    ...terms.map(([term, definition]): SheetRow => [
      text(term, { fontWeight: 'bold', alignVertical: 'top', ...RULE }),
      text(definition, { wrap: true, alignVertical: 'top', textColor: INK, ...RULE }),
    ]),
  ]

  return { data, widths: [26, 96] }
}

/* ── The workbook ─────────────────────────────────────────── */

/** One sheet as the library wants it, minus the picture, which
 *  `exportActivity` attaches — that keeps `buildWorkbook` free of the DOM. */
export type ActivitySheet = Omit<Sheet<Blob>, 'images'>

export interface Workbook {
  fileName: string
  sheets: ActivitySheet[]
  /** Where the picture is anchored on sheet 1, 1-based. */
  chartRow: number
  chartTitle: string
}

export interface BuildOptions {
  report: ActivityReport
  /** The cut on screen. The file must show the same one. */
  byHour: boolean
  /** Injected so the builder stays pure and its test is not time-dependent. */
  generatedAt?: Date
}

/**
 * The file name: `faollik-2026-07-15_2026-08-20.xlsx`.
 *
 * The dates being in the name matters: these files pile up in a folder, and
 * nobody can tell which period `faollik(3).xlsx` belongs to.
 */
export function fileName(report: ActivityReport): string {
  return `${t('activity.export.file')}-${report.date_from}_${report.date_to}.xlsx`
}

/**
 * Report in, sheets out. **Pure** — no DOM, no library, no clock unless one is
 * handed in, so the whole layout is testable in Node.
 */
export function buildWorkbook({
  report,
  byHour,
  generatedAt = new Date(),
}: BuildOptions): Workbook {
  const meta: Meta = {
    period: t('activity.export.period', {
      from: isoDateLabel(report.date_from),
      to: isoDateLabel(report.date_to),
      count: report.days,
    }),
    scope: t('activity.export.agents', { count: report.agents.length }),
    generated: t('activity.export.generated', { value: formatDateTime(generatedAt) }),
  }

  const summary = summarySheet(report, meta)
  const agents = agentsSheet(report, meta)
  const series = seriesSheet(report, byHour)
  const glossary = glossarySheet(report.callback_window_hours)

  return {
    fileName: fileName(report),
    chartRow: summary.chartRow,
    chartTitle: byHour ? t('activity.chartTitleHour') : t('activity.chartTitle'),
    sheets: [
      {
        data: summary.data,
        sheet: t('activity.export.sheetSummary'),
        columns: summary.widths.map((width) => ({ width })),
        /* ⚠️ GRIDLINES ARE OFF ON EVERY SHEET. A grey grid makes everything in
           the file look like a raw table; without it the only lines the eye
           sees are the ones drawn on purpose and the sheet reads as a
           document. `landscape` is for print: thirteen columns split across
           two pages in portrait. */
        showGridLines: false,
        orientation: 'landscape',
      },
      {
        data: agents.data,
        sheet: t('activity.export.sheetAgents'),
        columns: agents.widths.map((width) => ({ width })),
        showGridLines: false,
        orientation: 'landscape',
        /* Title block (3 rows) + the header row = 4. Frozen so the column
           names stay put while scrolling — without it, thirteen columns in and
           nobody knows which number belongs to which. The first column is
           frozen too, so the employee's name stays visible when scrolling
           right. */
        stickyRowsCount: 4,
        stickyColumnsCount: 1,
      },
      {
        data: series.data,
        sheet: byHour ? t('activity.export.sheetHours') : t('activity.export.sheetDays'),
        columns: series.widths.map((width) => ({ width })),
        showGridLines: false,
        stickyRowsCount: 3,
      },
      {
        data: glossary.data,
        sheet: t('activity.export.sheetGlossary'),
        columns: glossary.widths.map((width) => ({ width })),
        showGridLines: false,
      },
    ],
  }
}

export interface ActivityExportOptions extends BuildOptions {
  /** The series HIDDEN on screen — they stay out of the picture too. Seeing a
   *  line one has just switched off reappear in the file is the file failing to
   *  be a copy of the screen. */
  hidden?: ReadonlySet<SeriesKey>
}

/** The picture, or `null` — in which case the export carries on without it. */
async function chart(
  report: ActivityReport,
  byHour: boolean,
  hidden: ReadonlySet<SeriesKey>,
  title: string,
): Promise<ChartImage | null> {
  const points = byHour
    ? report.hours_series.map((row) => ({
        label: `${String(row.hour).padStart(2, '0')}:00`,
        values: row as unknown as Record<SeriesKey, number>,
      }))
    : report.days_series.map((row) => ({
        // `dd.MM` — fits even across 30 days
        label: `${row.day.slice(8, 10)}.${row.day.slice(5, 7)}`,
        values: row as unknown as Record<SeriesKey, number>,
      }))

  try {
    return await renderChartImage({
      points,
      series: SERIES.filter((item) => !hidden.has(item.key)).map((item) => ({
        key: item.key,
        label: t(item.labelKey),
        hex: item.hex,
        area: item.area,
      })),
      title,
    })
  } catch {
    return null
  }
}

export async function exportActivity({
  report,
  byHour,
  generatedAt,
  hidden = new Set<SeriesKey>(),
}: ActivityExportOptions): Promise<void> {
  const workbook = buildWorkbook({ report, byHour, generatedAt })
  const image = await chart(report, byHour, hidden, workbook.chartTitle)

  const writeXlsxFile = (await import('write-excel-file/browser')).default
  const [summary, ...rest] = workbook.sheets
  if (!summary) return

  const sheets: Sheet<Blob>[] = [
    {
      ...summary,
      /* The picture floats ABOVE the cells; the rows beneath it are empty. */
      images: image
        ? [
            {
              content: image.blob,
              contentType: 'image/png',
              width: image.width,
              height: image.height,
              dpi: image.dpi,
              anchor: { row: workbook.chartRow, column: 1 },
              title: workbook.chartTitle,
            },
          ]
        : undefined,
    },
    ...rest,
  ]

  await writeXlsxFile(sheets).toFile(workbook.fileName)
}
