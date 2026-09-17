/**
 * A sale's date, and a sale's money. Both rendered ONE way across the module.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ A DEFECT FIXED IN THE PORT, not carried across.
 *
 * `sales.occurred_on` is a DATE with no clock, and the source rendered it by
 * appending `T00:00:00` to the string before parsing:
 *
 *     formatFullDate(`${row.occurred_on}T00:00:00`)   // BonviZvonki
 *
 * An ISO string with no zone is parsed in the BROWSER's zone, and that source
 * formatted in the browser's zone as well, so the two cancelled out. This
 * panel deliberately renders every instant in Asia/Tashkent instead
 * (`shared/lib/format.ts`, SPEC §5.3) — a manager abroad must read the same
 * clock as the salesperson. Carrying the `T00:00:00` here would combine the
 * two: for a reader east of UTC+5 — Almaty, Bangkok, Seoul — `2026-08-12`
 * would be parsed as local midnight, i.e. BEFORE Tashkent midnight, and the
 * cell would print the 11th.
 *
 * A bare `YYYY-MM-DD` parses as UTC midnight, which in Asia/Tashkent (UTC+5)
 * is 05:00 the SAME day, whatever the browser's own zone. So the string is
 * passed through untouched and the date is right everywhere.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { EM_DASH, formatCount, formatDate } from '@/shared/lib/format'

/**
 * A sale's date, or the calendar date of an instant.
 *
 * Takes both on purpose: `occurred_on` and `previous_sale_on` are dates,
 * `last_call_at` is an instant, and the sentences in `reason.ts` mix them in
 * one line. Both end up as an Asia/Tashkent calendar date.
 */
export function formatSaleDate(value: string): string {
  return formatDate(value)
}

/**
 * A calendar date moved by N days, as `YYYY-MM-DD`.
 *
 * The arithmetic is done in UTC on purpose. These are calendar dates, not
 * instants, and `setDate()` on a local-zone Date crosses a DST boundary or a
 * zone offset and lands a day out. UTC has neither, and the server reads the
 * value as an Asia/Tashkent calendar date either way.
 */
export function shiftDay(day: string, days: number): string {
  const at = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(at.getTime())) return day
  at.setUTCDate(at.getUTCDate() + days)
  return at.toISOString().slice(0, 10)
}

/**
 * Money, in dollars.
 *
 * ⚠️ THE DOLLAR FIGURE IS THE PRIMARY ONE and the document's own currency is
 * secondary — comparison is only meaningful in one currency, and SAP supplies
 * the conversion itself. Rounded to whole dollars: cents answer no question on
 * a screen whose smallest interesting number is a ticket limit.
 *
 * `null` renders an em dash, never `0 $`: "SAP's cell was empty" and "this
 * sale was worth nothing" are different statements, and only one of them is
 * ever true.
 */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH
  return `${formatCount(Math.round(value))} $`
}
