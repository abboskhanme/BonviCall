/**
 * Display formatting: phone numbers, instants, durations.
 *
 * Lives in `shared/lib` rather than inside a module because the calls list, the
 * call card, the device pages and every report render the same three things and
 * must render them identically (CONVENTIONS-CLIENT.md §1).
 *
 * The phone rules are adopted from `../BonviZvonki/services/web/src/shared/lib/
 * phone.ts`, with its comments translated to English (CONVENTIONS.md §14 —
 * copying a file from that repo brings its Uzbek comments with it, and that is
 * a violation here).
 */

/** Uzbekistan's country calling code, without the `+`. */
const UZ_COUNTRY = '998'

/** The national part: operator code plus seven digits. */
const NATIONAL_DIGITS = 9

/** What a table cell shows where there is no value at all. */
export const EM_DASH = '—'

/**
 * Group the national part `981234567` into `98 123 45 67`.
 *
 * The split is 2-3-2-2 because that is how the number is spoken and read in
 * Uzbekistan. A 3-3-3 split would hide the operator code, which is the part a
 * reader recognises at a glance.
 */
function groupNational(digits: string): string {
  return [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 7), digits.slice(7)]
    .filter(Boolean)
    .join(' ')
}

/**
 * `+998981234567` → `+998 98 123 45 67`; `981234567` → `98 123 45 67`.
 *
 * **An unrecognised format is returned untouched.** Only two shapes are
 * reformatted: twelve digits starting with 998, and a bare nine-digit national
 * part. Prettifying anything else is dangerous — a foreign number
 * (`+971 50 123 4567`) chopped into Uzbek groups reads as a different number.
 *
 * Returns `null` for an empty value so the caller decides what to show; the
 * server stores an unparseable number raw with a NULL key rather than
 * rejecting the call (SPEC §4.0), so `null` genuinely reaches this function.
 */
export function formatPhone(value: string | null | undefined): string | null {
  const raw = (value ?? '').trim()
  if (!raw) return null

  const digits = raw.replace(/\D/g, '')

  if (digits.length === NATIONAL_DIGITS) return groupNational(digits)

  if (digits.length === UZ_COUNTRY.length + NATIONAL_DIGITS && digits.startsWith(UZ_COUNTRY)) {
    return `+${UZ_COUNTRY} ${groupNational(digits.slice(UZ_COUNTRY.length))}`
  }

  return raw
}

/**
 * The one time zone the panel renders in (SPEC §5.3).
 *
 * Not the browser's: a manager opening the panel from abroad must read the same
 * clock as the salesperson whose call it is, and every business date in this
 * system (`date_from`/`date_to`, the working-hours rules) is an Asia/Tashkent
 * calendar date.
 */
export const DISPLAY_TIME_ZONE = 'Asia/Tashkent'

type DateLike = string | number | Date

function toDate(value: DateLike): Date {
  return value instanceof Date ? value : new Date(value)
}

/**
 * Read the pieces of an instant in Asia/Tashkent.
 *
 * Built from `formatToParts` rather than `toLocaleString('uz-UZ')` for the
 * reason BonviZvonki documents: V8's `uz-UZ` locale renders months as `M04`.
 * Numeric parts in a fixed order sidestep the locale entirely.
 *
 * Exported for `shared/lib/xlsx.ts` alone, which needs the NUMBERS and not a
 * formatted string: Excel stores an instant as a serial number and carries no
 * time zone of its own, so an exported file has to be built from the same
 * Tashkent wall clock the screen showed. Everything else formats with
 * `formatDate` / `formatDateTime`.
 */
export function zonedParts(value: DateLike, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: DISPLAY_TIME_ZONE,
    hour12: false,
    ...options,
  })
  const parts: Record<string, string> = {}
  for (const part of formatter.formatToParts(toDate(value))) parts[part.type] = part.value
  return parts
}

function isValid(value: DateLike): boolean {
  return !Number.isNaN(toDate(value).getTime())
}

/** `05/09/2026` */
export function formatDate(value: DateLike): string {
  if (!isValid(value)) return EM_DASH
  const p = zonedParts(value, { day: '2-digit', month: '2-digit', year: 'numeric' })
  return `${p.day}/${p.month}/${p.year}`
}

/** `14:03` */
export function formatTime(value: DateLike): string {
  if (!isValid(value)) return EM_DASH
  const p = zonedParts(value, { hour: '2-digit', minute: '2-digit' })
  return `${p.hour}:${p.minute}`
}

/** `05/09/2026 14:03` — what a table cell shows. */
export function formatDateTime(value: DateLike): string {
  if (!isValid(value)) return EM_DASH
  return `${formatDate(value)} ${formatTime(value)}`
}

/** `formatDateTime` for a value that may be absent. */
export function formatDateTimeOrDash(value: string | null | undefined): string {
  return value ? formatDateTime(value) : EM_DASH
}

/**
 * The `title=` text: seconds and the UTC offset, so the offset is visible on
 * hover (SPEC §5.3) and a reader can tell 14:03 Tashkent from 14:03 anywhere.
 * `05/09/2026 14:03:11 GMT+5`
 */
export function formatInstantTitle(value: DateLike): string {
  if (!isValid(value)) return EM_DASH
  const p = zonedParts(value, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZoneName: 'shortOffset',
  })
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}:${p.second} ${p.timeZoneName ?? ''}`.trim()
}

const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3600

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/**
 * `mm:ss`, and `h:mm:ss` once the call passes an hour (SPEC §5.3).
 *
 * `duration_sec` is `NOT NULL DEFAULT 0` and a CHECK makes it 0 for everything
 * a nobody answered, so 0 is a real value and renders as `00:00` rather than a
 * dash — "the call lasted no time" and "we do not know how long it lasted" are
 * different statements.
 */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined || !Number.isFinite(totalSeconds)) {
    return EM_DASH
  }
  const seconds = Math.max(0, Math.trunc(totalSeconds))
  const hours = Math.floor(seconds / SECONDS_PER_HOUR)
  const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE)
  const rest = seconds % SECONDS_PER_MINUTE
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(rest)}`
    : `${pad(minutes)}:${pad(rest)}`
}

/**
 * A UUID shortened for a table cell: `a1b2c3d4…`.
 *
 * Only ever a fallback for a name that could not be resolved, and never the
 * primary label — a raw identifier in a column a human reads is a bug with a
 * border.
 */
export function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

/**
 * A thousands separator that does not depend on ICU locale data being present.
 *
 * `NON_BREAKING_SPACE` is written as an escape rather than typed: an invisible
 * separator in a source file is a character nobody can see in review and nobody
 * can grep for, and this project has already lost one test to a thin space
 * pasted in by accident.
 */
const NON_BREAKING_SPACE = '\u00A0'

/** `1234567` → `1 234 567`. */
export function formatCount(value: number): string {
  return String(Math.trunc(value)).replace(/\B(?=(\d{3})+(?!\d))/g, NON_BREAKING_SPACE)
}

const BYTES_PER_STEP = 1024
/** Binary units, because every source of these numbers is a filesystem or a
 *  queue depth: the server reports `queue_bytes` and `free_storage_bytes`
 *  straight from Android, which counts in KiB. */
export const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

/** `1536` → `1.5 KB`. Unit symbols stay Latin: they are read the same in
 *  Uzbek and translating them would make them harder, not easier. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return EM_DASH
  let value = Math.max(0, bytes)
  let step = 0
  while (value >= BYTES_PER_STEP && step < BYTE_UNITS.length - 1) {
    value /= BYTES_PER_STEP
    step += 1
  }
  const rounded = value >= 100 || step === 0 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded}${NON_BREAKING_SPACE}${BYTE_UNITS[step]}`
}

/**
 * How long ago, as a unit and a count — never as a sentence.
 *
 * The wording is Uzbek and belongs in `uz.json` (CONVENTIONS.md §14), so this
 * function stays language-free and the caller picks the key. That split is
 * what lets "last heard from" read as *"3 daqiqa oldin"* on the device page
 * and as something else on a report without two copies of the arithmetic.
 *
 * `future` is a real case and not defensive coding: a handset with a wrong
 * clock reports a heartbeat timestamped tomorrow, and a device page that
 * renders that as "-1 daqiqa oldin" hides exactly the skew it exists to show.
 */
export type RelativeUnit = 'now' | 'minute' | 'hour' | 'day' | 'future'

export interface Relative {
  unit: RelativeUnit
  value: number
}

const SECONDS_PER_DAY = 86_400

export function relativeTo(value: DateLike, now: DateLike = new Date()): Relative {
  const seconds = Math.round((toDate(now).getTime() - toDate(value).getTime()) / 1000)
  if (seconds < -60) return { unit: 'future', value: Math.abs(seconds) }
  if (seconds < 60) return { unit: 'now', value: 0 }
  if (seconds < SECONDS_PER_HOUR) {
    return { unit: 'minute', value: Math.floor(seconds / SECONDS_PER_MINUTE) }
  }
  if (seconds < SECONDS_PER_DAY) return { unit: 'hour', value: Math.floor(seconds / SECONDS_PER_HOUR) }
  return { unit: 'day', value: Math.floor(seconds / SECONDS_PER_DAY) }
}
