/**
 * The house style for every Excel file this product writes.
 *
 * Ported from `../BonviZvonki/services/web/src/shared/lib/xlsx.ts`, comments
 * translated (CONVENTIONS.md §14), with one deliberate change of behaviour —
 * the time zone, below.
 *
 * WHY A MODULE OF ITS OWN. When each export writes its own colours and
 * formats the files drift apart: the heading is navy in one report and grey in
 * the next, a percentage reads `29,7%` here and `0,297` there. A manager opens
 * them side by side, and two files from one company have to look like one
 * company wrote them.
 *
 * ── WHAT MAKES A FILE READABLE ────────────────────────────────
 *
 *   1. NO ZEBRA. Shading every second row over ten-plus columns tires the eye
 *      and makes the file look machine-generated. A hairline rule under each
 *      row does the same job and leaves the sheet quiet.
 *   2. GRID LINES OFF (`showGridLines: false` at the call site). The grey grid
 *      makes a sheet look like raw data; with it off the only lines visible
 *      are the ones we drew on purpose.
 *   3. COLOUR IS MEANING. Red only for a problem, green only for a good
 *      outcome. A cell coloured to look nice is a false signal.
 *   4. A NUMBER STAYS A NUMBER. Money, percentages and durations are written
 *      as formatted NUMBERS, never as text — otherwise neither sorting nor
 *      summing works in Excel, which is the first thing a manager does.
 *   5. ONE SHEET, ONE JOB: the summary, the table, a cut, the glossary.
 *
 * ⚠️ `modules/activity/export.ts` still carries its own private copy of this
 * kit. It was written before this file existed and is left untouched on
 * purpose (work additively); the values here are reconciled with it cell for
 * cell, so the two produce the same-looking file. Moving that module onto this
 * kit is a separate change with no behaviour in it.
 *
 * The library itself is never imported here — only its TYPES, which cost
 * nothing at runtime. Every caller loads it dynamically when a button is
 * pressed.
 */
import type { CellObject, Row } from 'write-excel-file/browser'

import { DISPLAY_TIME_ZONE, zonedParts } from './format'

/** A cell without its value: what the helpers below take as styling. */
export type CellStyle = Omit<CellObject, 'value' | 'type'>

/* ── Colours ──────────────────────────────────────────────────
   The light-theme tokens of `src/index.css`. Excel has no theme, so a file
   always uses the light values and reads as a continuation of the screen: a
   red number is the same red in both. */
export const NAVY = '#215A8C' // --accent
export const GOOD = '#1E8052' // --good
export const WARN = '#B35C05' // --warn
export const BAD = '#CC1E36' // --bad
export const INK = '#151D28' // --text
export const MUTED = '#677383' // --muted
/** The rule between rows — a hairline, NOT a zebra (rule 1 above). */
export const RULE_COLOR = '#E3E7ED' // --border
/** The fill behind a total row and other lightly set-off places. */
export const BAND = '#F4F6F9' // --surface-2

/* ── Number formats ───────────────────────────────────────── */

/** Thousands separated. */
export const NUM = '#,##0'
/**
 * Money — two decimals.
 *
 * The database keeps three (`numeric(18,3)`); the third is never read in a
 * report and only widens the column.
 */
export const MONEY = '#,##0.00'
/** Percent: the wire carries 0-100, Excel expects a fraction. */
export const PCT = '0.0%'
export const DATE = 'dd.mm.yyyy'
export const DATETIME = 'dd.mm.yyyy hh:mm'

/* ── Cells ────────────────────────────────────────────────────
   Each helper answers "no value" with an EMPTY cell that still carries the
   row's styling — so a missing figure leaves a gap in the table rather than a
   zero, which would read as a measured nothing. */

export function text(value: string | null | undefined, style: CellStyle = {}): CellObject {
  if (!value) return { ...style }
  return { value, type: String, ...style }
}

export function num(value: number | null | undefined, style: CellStyle = {}): CellObject {
  if (value === null || value === undefined) return { ...style }
  return { value, type: Number, format: NUM, ...style }
}

export function money(value: number | null | undefined, style: CellStyle = {}): CellObject {
  if (value === null || value === undefined) return { ...style }
  return { value, type: Number, format: MONEY, ...style }
}

/** A percentage. The value arrives on the 0-100 scale, as on screen. */
export function pct(value: number | null | undefined, style: CellStyle = {}): CellObject {
  if (value === null || value === undefined) return { ...style }
  return { value: value / 100, type: Number, format: PCT, ...style }
}

/* ── Instants: why the value is rebuilt ───────────────────────
   `write-excel-file` turns a `Date` into Excel's serial number through
   `getTime()`, which means the file carries UTC. A call shown as `14:22` on
   screen would open as `09:22` in the file — and nobody would notice, because
   09:22 is a believable time too.

   ⚠️ THE ONE DELIBERATE DIFFERENCE FROM THE SOURCE. BonviZvonki rebuilt the
   value from the BROWSER's calendar fields (`getHours()`), because that panel
   also rendered in the browser's zone, so the file and the screen agreed. This
   panel renders every instant in Asia/Tashkent instead (`format.ts`,
   SPEC §5.3) — a manager abroad reads the same clock as the salesperson — so
   the file has to be built from the TASHKENT wall clock. Carrying the source's
   version across would have made the file disagree with the screen for exactly
   the readers the rule exists for. */

/** The Asia/Tashkent wall clock of an instant, re-expressed as a UTC `Date`. */
function wallClock(value: Date, withTime: boolean): Date {
  const p = zonedParts(
    value,
    withTime
      ? {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }
      : { year: 'numeric', month: '2-digit', day: '2-digit' },
  )
  return new Date(
    Date.UTC(
      Number(p.year),
      Number(p.month) - 1,
      Number(p.day),
      withTime ? Number(p.hour) : 0,
      withTime ? Number(p.minute) : 0,
      withTime ? Number(p.second) : 0,
    ),
  )
}

/** `YYYY-MM-DD` — a date with no clock, which is how SAP gives a sale's day. */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/**
 * A date cell, from either a `YYYY-MM-DD` string or an instant.
 *
 * ⚠️ `new Date('2026-08-20')` is UTC midnight, and for a bare date string that
 * is exactly right: Excel wants the calendar day and nothing else. An instant
 * is reduced to its Asia/Tashkent calendar day instead — a call at 03:00
 * Tashkent would otherwise print as the previous day.
 */
export function date(
  value: string | Date | null | undefined,
  style: CellStyle = {},
): CellObject {
  if (!value) return { ...style }
  if (typeof value === 'string' && DATE_ONLY.test(value)) {
    return { value: new Date(value), type: Date, format: DATE, ...style }
  }
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return { ...style }
  return { value: wallClock(parsed, false), type: Date, format: DATE, ...style }
}

/**
 * A date AND time cell, in Asia/Tashkent (`DISPLAY_TIME_ZONE`).
 *
 * The call time is the most delicate column in a sales file: it is what a
 * manager reads to answer "was there a conversation before the sale?". A value
 * five hours out would break that judgement silently.
 */
export function datetime(
  value: string | Date | null | undefined,
  style: CellStyle = {},
): CellObject {
  if (!value) return { ...style }
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return { ...style }
  return { value: wallClock(parsed, true), type: Date, format: DATETIME, ...style }
}

/** Stated so a reader of this file can see which clock it is written in. */
export const EXPORT_TIME_ZONE = DISPLAY_TIME_ZONE

/* ── Styles ───────────────────────────────────────────────── */

/** A sheet's title. */
export const TITLE: CellStyle = { fontWeight: 'bold', fontSize: 15, textColor: INK }
/** The grey lines under it: period, filter, when it was downloaded. */
export const META: CellStyle = { fontSize: 10, textColor: MUTED }
/** A section heading — small, bold, ruled underneath. Unlike a large coloured
 *  title it divides the sheet without demanding attention. */
export const SECTION: CellStyle = {
  fontWeight: 'bold',
  fontSize: 9,
  textColor: MUTED,
  bottomBorderStyle: 'thin',
  bottomBorderColor: RULE_COLOR,
}

/** A table header. `align` is added per column: a numeric column is right
 *  aligned and its heading has to sit over the figures. */
export const HEADER: CellStyle = {
  fontWeight: 'bold',
  fontSize: 10,
  textColor: '#FFFFFF',
  backgroundColor: NAVY,
  alignVertical: 'center',
  wrap: true,
  height: 34,
}

/** The hairline under every data cell. */
export const RULE: CellStyle = {
  bottomBorderStyle: 'thin',
  bottomBorderColor: RULE_COLOR,
}

/** The total row. */
export const TOTAL: CellStyle = {
  fontWeight: 'bold',
  backgroundColor: BAND,
  topBorderStyle: 'medium',
  topBorderColor: NAVY,
}

/* ── Structures ───────────────────────────────────────────── */

/** One cell spread across several columns — for titles and notes. */
export function span(cell: CellObject, width: number): Row {
  return [{ ...cell, columnSpan: width }, ...Array.from({ length: width - 1 }, () => null)]
}

/**
 * A long note, in a spanned cell, with its HEIGHT worked out.
 *
 * ⚠️ Excel does not auto-fit the height of a MERGED cell (it does for an
 * ordinary one). Without an explicit height only the first line of a
 * multi-line note is visible.
 *
 * `perLine` is the spanned columns' combined width in characters, taken a
 * little under the sum of `widths`: a word that wraps whole leaves the line
 * short.
 */
export function note(value: string, style: CellStyle, width: number, perLine: number): Row {
  const lines = Math.max(1, Math.ceil(value.length / perLine))
  return span(text(value, { ...style, wrap: true, height: lines * 15 + 3 }), width)
}

/**
 * The rows of a two-column "term → what it means" sheet.
 *
 * Every report needs one: the file travels by email and whoever opens it may
 * never have seen the screen, where "window" or "R2" is explained in a hover.
 */
export function glossaryRows(terms: [string, string][]): Row[] {
  return terms.map(([term, definition]) => [
    text(term, { fontWeight: 'bold', alignVertical: 'top', ...RULE }),
    text(definition, { wrap: true, alignVertical: 'top', textColor: INK, ...RULE }),
  ])
}
