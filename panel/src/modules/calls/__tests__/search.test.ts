/**
 * The one-box search rule (`../search.ts`).
 *
 * The panel shows a single field and the server keeps two parameters, so this
 * function is the only place that decides which one a person's typing becomes.
 * Getting it wrong is silent: `q` over a phone number matches nothing, and
 * `remote_number` over a name matches nothing, and in both cases the page
 * shows a perfectly calm "nothing matches this filter". Hence a test per case
 * rather than a page test that would only prove one of them.
 */
import { describe, expect, it } from 'vitest'

import { searchParamFor } from '@/modules/calls/search'

describe('searchParamFor', () => {
  it('reads a spaced national number as a number', () => {
    expect(searchParamFor('90 111 22 33')).toEqual({ remote_number: '90 111 22 33' })
  })

  it('reads an E.164 number as a number', () => {
    expect(searchParamFor('+998901112233')).toEqual({ remote_number: '+998901112233' })
  })

  it('reads bare digits as a number', () => {
    expect(searchParamFor('901112233')).toEqual({ remote_number: '901112233' })
  })

  it('reads punctuation people actually paste as a number', () => {
    expect(searchParamFor('(90) 111-22-33')).toEqual({ remote_number: '(90) 111-22-33' })
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * Extensions, and why this is not a nicety.
   *
   * `core/phone.py::is_extension` gives `700` and `*700` no phone key on
   * purpose, and the server's `remote_number` filter then falls back to an
   * EXACT match on the raw string — which is how extension calls are found.
   * Routing these to `q` (an ILIKE over contact names) loses them entirely,
   * and the line directory exists to classify exactly these lines.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('reads a PBX extension as a number', () => {
    expect(searchParamFor('700')).toEqual({ remote_number: '700' })
  })

  it('reads a starred extension as a number', () => {
    expect(searchParamFor('*700')).toEqual({ remote_number: '*700' })
    expect(searchParamFor('#123')).toEqual({ remote_number: '#123' })
  })

  it('reads one word as a contact name', () => {
    expect(searchParamFor('Aziz')).toEqual({ q: 'Aziz' })
  })

  it('reads two words as a contact name', () => {
    expect(searchParamFor('Aziz Karimov')).toEqual({ q: 'Aziz Karimov' })
  })

  /**
   * The ambiguous one. `A1` has a digit in it, and a rule that only asked
   * "does it contain digits" would send it to `remote_number`, where it can
   * never match — the key is nine digits. One letter is enough to make it a
   * name.
   */
  it('sends anything holding a letter to the name search', () => {
    expect(searchParamFor('A1')).toEqual({ q: 'A1' })
    expect(searchParamFor('998-uy')).toEqual({ q: '998-uy' })
  })

  /**
   * Both sides of the threshold, so the constant is pinned rather than merely
   * explained. `MIN_PHONE_DIGITS` is 1: one digit and no letters is a number,
   * no digits at all is not. Raise it to 4 and the first of these fails — the
   * regression that made `700` unfindable.
   */
  it('needs one digit to be a number, and one is enough', () => {
    expect(searchParamFor('5')).toEqual({ remote_number: '5' })
    expect(searchParamFor('0')).toEqual({ remote_number: '0' })
    expect(searchParamFor('12')).toEqual({ remote_number: '12' })
  })

  it('is not a number when there is no digit in it at all', () => {
    expect(searchParamFor('+')).toEqual({ q: '+' })
    expect(searchParamFor('---')).toEqual({ q: '---' })
  })

  /**
   * The trade this rule takes, written down as a test so it is a decision and
   * not a surprise: a contact-name search for pure digits no longer works.
   * A contact called `700` is not a thing; a call to extension `700` is.
   */
  it('sends a purely numeric search to the number filter, never to the name', () => {
    expect(searchParamFor('2026')).toEqual({ remote_number: '2026' })
  })

  it('is no filter at all when nothing was typed', () => {
    expect(searchParamFor('')).toBeNull()
    expect(searchParamFor('   ')).toBeNull()
  })

  it('trims what it passes on, so a stray space is not a different filter', () => {
    expect(searchParamFor('  Aziz  ')).toEqual({ q: 'Aziz' })
    expect(searchParamFor('  901112233 ')).toEqual({ remote_number: '901112233' })
  })

  /**
   * The value travels as typed: `phone_key` on the server strips the spacing,
   * so normalising here would be the same rule written twice — and the two
   * copies would drift (CONVENTIONS.md §7).
   */
  it('never rewrites the number it was given', () => {
    expect(searchParamFor('+998 90 111 22 33')).toEqual({ remote_number: '+998 90 111 22 33' })
  })
})
