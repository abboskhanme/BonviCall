/**
 * The Uzbek catalogue, read as a whole (T105).
 *
 * Strings get added one feature at a time, which is how a catalogue ends up
 * with three words for one thing and a dozen entries nothing renders. These
 * checks are the pass that would otherwise have to be done by eye every time.
 *
 * They are deliberately mechanical. Consistency of TONE is a review question
 * and stays one; what is automated here is the part a person cannot reliably
 * do — reading 777 strings and remembering all of them.
 */
import { describe, expect, it } from 'vitest'

import uz from '@/shared/i18n/uz.json'
import { messageKeys, t } from '@/shared/i18n'
import { ERROR_CODES } from '@/shared/api/errorCodes.gen'

const CATALOGUE: Record<string, string> = uz

describe('completeness', () => {
  it('has an Uzbek entry for every error code the server can emit', () => {
    // Also enforced by errorCatalogue.test.ts against `messageForError`; here
    // it is the catalogue's own invariant rather than the renderer's.
    const missing = ERROR_CODES.filter((code) => !(`errors.${code}` in CATALOGUE))
    expect(missing).toEqual([])
  })

  it('has no empty strings', () => {
    const empty = messageKeys().filter((key) => CATALOGUE[key]?.trim() === '')
    expect(empty).toEqual([])
  })

  it('interpolates every placeholder it declares', () => {
    // `t()` leaves an unknown `{name}` in place, so a typo in a placeholder
    // ships as literal braces on screen. Each is at least well-formed here.
    const malformed = messageKeys().filter((key) => {
      const value = CATALOGUE[key] ?? ''
      return /\{[^}]*$/.test(value) || /^[^{]*\}/.test(value.replace(/\{[^}]*\}/g, ''))
    })
    expect(malformed).toEqual([])
  })
})

describe('no English leaking through', () => {
  /**
   * Words that would only appear if an English sentence had been pasted in.
   * Deliberately small and specific: Uzbek borrows plenty of Latin-script
   * technical terms — `Wi-Fi`, `API`, `SHA-256`, `legacy28` — and those are
   * correct, so a blanket "any Latin word" rule would be wrong.
   */
  const ENGLISH = [
    'the', 'and', 'with', 'from', 'this', 'that', 'error', 'failed', 'invalid',
    'please', 'device', 'call', 'user', 'settings', 'report', 'update',
    'required', 'unknown', 'success', 'warning', 'cancel', 'delete', 'save',
  ]

  it('contains no English prose', () => {
    const offenders: string[] = []
    for (const key of messageKeys()) {
      const value = CATALOGUE[key] ?? ''
      // Placeholders are English by design — `{count}`, `{name}` — and are
      // never rendered, so they are stripped before looking.
      const text = value.replace(/\{[^}]*\}/g, ' ').toLowerCase()
      const words = text.match(/[a-z']+/g) ?? []
      if (words.some((word) => ENGLISH.includes(word))) offenders.push(`${key}: ${value}`)
    }
    expect(offenders).toEqual([])
  })
})

describe('errors say what to do', () => {
  /**
   * An error a user reads should end a sentence, not a noun phrase. This
   * catches the common regression: a code added in a hurry with a two-word
   * gloss that tells nobody anything.
   */
  it('gives every error code a real sentence', () => {
    const tooShort = ERROR_CODES.map((code) => `errors.${code}`)
      .filter((key) => (CATALOGUE[key] ?? '').length < 20)
    expect(tooShort).toEqual([])
  })

  it('ends every error message with a full stop', () => {
    const unpunctuated = ERROR_CODES.map((code) => `errors.${code}`).filter(
      (key) => !/[.!?]$/.test(CATALOGUE[key] ?? ''),
    )
    expect(unpunctuated).toEqual([])
  })
})

describe('nothing renders a key', () => {
  it('resolves every key to text that is not the key itself', () => {
    for (const key of messageKeys()) {
      expect(t(key as Parameters<typeof t>[0])).not.toBe(key)
    }
  })
})
