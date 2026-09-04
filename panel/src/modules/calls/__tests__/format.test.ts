/**
 * The display formatters.
 *
 * Phone formatting is adopted from BonviZvonki, including the rule that matters
 * most: **an unrecognised format is returned untouched.** A foreign number
 * chopped into Uzbek 2-3-2-2 groups reads as a different number, and "the panel
 * showed me the wrong number" is not a formatting bug, it is a data bug as far
 * as anyone using it is concerned.
 *
 * Times are pinned to Asia/Tashkent (SPEC §5.3) rather than to the machine's
 * clock, so this file fails on a CI runner in UTC if that ever regresses.
 */
import { describe, expect, it } from 'vitest'

import {
  EM_DASH,
  formatCount,
  formatDate,
  formatDateTime,
  formatDuration,
  formatInstantTitle,
  formatPhone,
} from '@/shared/lib/format'

describe('formatPhone', () => {
  it('groups a national number 2-3-2-2, the way it is spoken', () => {
    expect(formatPhone('901112233')).toBe('90 111 22 33')
  })

  it('groups an E.164 Uzbek number and keeps the country code', () => {
    expect(formatPhone('+998901112233')).toBe('+998 90 111 22 33')
    expect(formatPhone('998901112233')).toBe('+998 90 111 22 33')
    expect(formatPhone('(+99893) 6620700')).toBe('+998 93 662 07 00')
  })

  it('leaves a shape it does not recognise exactly as it arrived', () => {
    // A foreign number split into Uzbek groups would read as another number.
    expect(formatPhone('+971 50 123 4567')).toBe('+971 50 123 4567')
    // A four-digit extension is not a number with a key (SPEC §3.5).
    expect(formatPhone('1234')).toBe('1234')
  })

  it('returns null when there is nothing, so the caller picks the wording', () => {
    expect(formatPhone(null)).toBeNull()
    expect(formatPhone('')).toBeNull()
    expect(formatPhone('   ')).toBeNull()
  })
})

describe('instants', () => {
  // 09:03 UTC is 14:03 in Tashkent (UTC+5, no DST).
  const utcInstant = '2026-09-05T09:03:11Z'

  it('renders in Asia/Tashkent regardless of where the browser is', () => {
    expect(formatDate(utcInstant)).toBe('05/09/2026')
    expect(formatDateTime(utcInstant)).toBe('05/09/2026 14:03')
  })

  it('reads the same instant however the offset was written on the wire', () => {
    expect(formatDateTime('2026-09-05T14:03:11+05:00')).toBe('05/09/2026 14:03')
  })

  it('puts the offset in the hover title, where SPEC §5.3 asks for it', () => {
    const title = formatInstantTitle(utcInstant)
    expect(title).toContain('14:03:11')
    expect(title).toContain('GMT+5')
  })

  it('does not render "Invalid Date" for a value it cannot parse', () => {
    expect(formatDateTime('not a date')).toBe(EM_DASH)
  })
})

describe('formatDuration', () => {
  it('renders mm:ss, and h:mm:ss past an hour', () => {
    expect(formatDuration(0)).toBe('00:00')
    expect(formatDuration(9)).toBe('00:09')
    expect(formatDuration(125)).toBe('02:05')
    expect(formatDuration(3725)).toBe('1:02:05')
  })

  it('keeps 0 as a real value, distinct from "unknown"', () => {
    // The CHECK constraint makes duration_sec 0 for every unanswered call, so
    // 0 is a fact and must not render as a dash.
    expect(formatDuration(0)).not.toBe(EM_DASH)
    expect(formatDuration(null)).toBe(EM_DASH)
  })
})

describe('formatCount', () => {
  it('separates thousands with a non-breaking space', () => {
    // Non-breaking, so a total never wraps mid-number at the end of a line.
    expect(formatCount(1234567)).toBe('1\u00A0234\u00A0567')
    expect(formatCount(42)).toBe('42')
  })
})
