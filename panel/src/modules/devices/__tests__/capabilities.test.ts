/**
 * The capability matrix's colouring.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Three states look superficially alike and mean entirely different things,
 * and only two of them are anybody's problem:
 *
 *   `denied`              somebody said no. Fixable by asking again.
 *   `denied_permanently`  somebody said no twice. Needs a visit to Settings.
 *   `not_applicable`      the handset does not have the feature at all.
 *                         **Nobody's problem, and nothing to chase.**
 *
 * A matrix that rendered `not_applicable` as a fault would send an admin
 * hunting for a permission that does not exist on that phone — and the demo
 * fleet has nine of them, against three real denials.
 *
 * `granted_not_working` is the fourth, and it is red: Android reports the
 * permission as granted and an OEM layer refuses it anyway. That IS R3, and a
 * matrix showing it as a shade of "granted" would hide the one state this
 * page was built to catch.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { describe, expect, it } from 'vitest'

import {
  CAPABILITY_LABEL,
  CAPABILITY_STATE_LABEL,
  CAPABILITY_STATE_TONE,
} from '@/modules/devices/labels'
import { t } from '@/shared/i18n'

describe('what counts as a problem', () => {
  it('never colours "the phone does not have this" as a fault', () => {
    expect(CAPABILITY_STATE_TONE.not_applicable).toBe('neutral')
    expect(CAPABILITY_STATE_TONE.unknown).toBe('neutral')
  })

  it('colours a real denial as one', () => {
    expect(CAPABILITY_STATE_TONE.denied).toBe('warn')
    // Permanent denial cannot be fixed by asking again — it needs somebody to
    // open the phone's settings — so it is as loud as a broken capability.
    expect(CAPABILITY_STATE_TONE.denied_permanently).toBe('bad')
  })

  it('colours "granted but not working" red, because that is R3 itself', () => {
    expect(CAPABILITY_STATE_TONE.granted_not_working).toBe('bad')
    // Not a shade of granted.
    expect(CAPABILITY_STATE_TONE.granted_not_working).not.toBe(
      CAPABILITY_STATE_TONE.granted_working,
    )
  })
})

describe('wording', () => {
  it('gives denied and not-applicable different sentences', () => {
    // If these ever collapse into one string the colours stop mattering.
    expect(t(CAPABILITY_STATE_LABEL.denied)).not.toBe(t(CAPABILITY_STATE_LABEL.not_applicable))
    expect(t(CAPABILITY_STATE_LABEL.denied)).not.toBe(
      t(CAPABILITY_STATE_LABEL.denied_permanently),
    )
    expect(t(CAPABILITY_STATE_LABEL.granted_working)).not.toBe(
      t(CAPABILITY_STATE_LABEL.granted_not_working),
    )
  })

  it('translates every capability and every state', () => {
    for (const key of Object.values(CAPABILITY_LABEL)) {
      expect(t(key)).not.toBe(key)
    }
    for (const key of Object.values(CAPABILITY_STATE_LABEL)) {
      expect(t(key)).not.toBe(key)
    }
  })
})
