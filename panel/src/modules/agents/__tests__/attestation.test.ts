/**
 * When an admin may attest a number (T142, SPEC §9.3).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Attestation is the escape hatch for a binding the system could not prove,
 * and the danger is that it becomes the front door. An attested binding is a
 * person's word; a proven one is a fact the system established. If the button
 * is offered first, every time, every installation quietly becomes the weaker
 * kind and nobody can tell later which rests on which.
 *
 * So the two halves are both tested: it must be AVAILABLE when nothing else
 * can finish — which is the client's situation right now, a real handset stuck
 * with no MSISDN and no callback receiver — and UNAVAILABLE when an automatic
 * route could still succeed.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { describe, expect, it } from 'vitest'

import { attestStance, stanceReasonKey } from '@/modules/agents/attestation'
import type { components } from '@/shared/api/types.gen'

type Attempt = components['schemas']['EnrolmentAttemptResponse']
type Receiver = components['schemas']['ReceiverStatusResponse']

function attempt(overrides: Partial<Attempt> = {}): Attempt {
  return {
    id: 'attempt-1',
    kind: 'msisdn_check',
    outcome: 'msisdn_empty',
    step: null,
    created_at: '2026-09-05T09:00:00+05:00',
    agent_id: 'agent-1',
    number_id: 'number-1',
    installation_id: 'inst-1',
    device_model: 'Xiaomi Redmi 10C',
    app_version: '1.0.0',
    duration_ms: 400,
    ...overrides,
  }
}

const RECEIVER_UP: Receiver = {
  enrolment_possible: true,
  status: 'up',
  receiver_name: 'Receiver 1',
  receiver_msisdn: '+998901234567',
  active_receivers: 1,
}
const RECEIVER_DOWN: Receiver = {
  enrolment_possible: false,
  status: 'down',
  receiver_name: null,
  receiver_msisdn: null,
  active_receivers: 0,
}

describe('already bound: nothing to attest', () => {
  it('says so once a number is verified', () => {
    expect(
      attestStance({
        stage: 'number_verified',
        verifiedAt: '2026-09-05T09:00:00+05:00',
        attempts: [],
        receiver: RECEIVER_DOWN,
      }).kind,
    ).toBe('not_needed')
  })

  it('will not re-attest over a proven binding, even with the receiver down', () => {
    // Attesting over a fact would replace it with an opinion.
    expect(
      attestStance({
        stage: 'capturing',
        verifiedAt: '2026-09-05T09:00:00+05:00',
        attempts: [attempt()],
        receiver: RECEIVER_DOWN,
      }).kind,
    ).toBe('not_needed')
  })

  it('treats an existing attestation as bound too', () => {
    expect(
      attestStance({
        stage: 'verified_by_admin',
        verifiedAt: null,
        attempts: [],
        receiver: RECEIVER_DOWN,
      }).kind,
    ).toBe('not_needed')
  })
})

describe('an automatic route could still work', () => {
  it('holds back when nothing has failed and the callback is live', () => {
    // The admin cannot trigger route 1 from the panel — the phone does — so
    // offering attestation here would only be a way of not waiting.
    expect(
      attestStance({
        stage: 'installed',
        verifiedAt: null,
        attempts: [],
        receiver: RECEIVER_UP,
      }).kind,
    ).toBe('premature')
  })

  it('holds back while the receiver status is still unknown', () => {
    // Absence of news is not news: treating a slow request as "down" would
    // open the hatch on a loading state.
    expect(
      attestStance({
        stage: 'installed',
        verifiedAt: null,
        attempts: [],
        receiver: undefined,
      }).kind,
    ).toBe('premature')
  })

  it('does not count a SUCCESSFUL msisdn check as a failure', () => {
    expect(
      attestStance({
        stage: 'installed',
        verifiedAt: null,
        attempts: [attempt({ outcome: 'ok' })],
        receiver: RECEIVER_UP,
      }).kind,
    ).toBe('premature')
  })

  it('ignores a failure from a different route', () => {
    // A failed code redemption says nothing about whether the SIM can report
    // its own number.
    expect(
      attestStance({
        stage: 'installed',
        verifiedAt: null,
        attempts: [attempt({ kind: 'code_redeem', outcome: 'code_expired' })],
        receiver: RECEIVER_UP,
      }).kind,
    ).toBe('premature')
  })
})

describe('nothing automatic can finish: this is what it is for', () => {
  it('opens when the SIM reported no number', () => {
    const stance = attestStance({
      stage: 'installed',
      verifiedAt: null,
      attempts: [attempt({ outcome: 'msisdn_empty' })],
      receiver: RECEIVER_UP,
    })
    expect(stance).toEqual({ kind: 'offered', because: 'msisdn_failed' })
  })

  it('opens when the callback receiver is down', () => {
    // W12: the client has not provided an inbound receiver, so route 2 cannot
    // complete for anybody.
    const stance = attestStance({
      stage: 'installed',
      verifiedAt: null,
      attempts: [],
      receiver: RECEIVER_DOWN,
    })
    expect(stance).toEqual({ kind: 'offered', because: 'receiver_down' })
  })

  it('names both when both are gone — the live situation', () => {
    const stance = attestStance({
      stage: 'installed',
      verifiedAt: null,
      attempts: [attempt({ outcome: 'msisdn_empty' })],
      receiver: RECEIVER_DOWN,
    })
    expect(stance).toEqual({ kind: 'offered', because: 'both' })
  })

  it('opens on a number that came back belonging to somebody else', () => {
    expect(
      attestStance({
        stage: 'installed',
        verifiedAt: null,
        attempts: [attempt({ outcome: 'number_mismatch' })],
        receiver: RECEIVER_UP,
      }).kind,
    ).toBe('offered')
  })
})

describe('the reason travels', () => {
  it('maps each cause to its own sentence', () => {
    // Three distinct keys: the admin should learn WHICH route failed, or the
    // offer reads as a shortcut somebody took because it was quicker.
    const keys = (['msisdn_failed', 'receiver_down', 'both'] as const).map((because) =>
      stanceReasonKey({ kind: 'offered', because }),
    )
    expect(new Set(keys).size).toBe(3)
  })
})
