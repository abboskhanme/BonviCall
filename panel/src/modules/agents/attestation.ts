/**
 * When an admin may attest a number, and when they should not (T142, SPEC §9.3).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Attestation is the escape hatch for a binding the system could not prove.
 * Number verification has two automatic routes and both can be unavailable:
 *
 *   route 1 — the SIM's own MSISDN, which many Uzbek SIMs simply do not
 *             report, so `line1_number` comes back empty;
 *   route 2 — the callback, where the phone dials a number we watch. That
 *             needs an inbound receiver, and there is not one (W12).
 *
 * With both gone there is no way to finish enrolment at all, which is where
 * the client is right now: a real handset at `installed`, no verification
 * method, receiver down.
 *
 * **But it must not be a shortcut past a route that would have worked.** An
 * attested binding is a person's word; a proven one is a fact the system
 * established. Offering the button first, every time, would quietly turn every
 * installation into the weaker kind — and nobody would be able to tell later
 * which was which.
 *
 * So the stance is computed rather than assumed, and the page says WHY the
 * escape hatch is open.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import type { components } from '@/shared/api/types.gen'

type FunnelStage = components['schemas']['FunnelStage']
type EnrolmentAttempt = components['schemas']['EnrolmentAttemptResponse']
type ReceiverStatus = components['schemas']['ReceiverStatusResponse']

/** Stages at which the number is already bound; nothing to attest. */
const VERIFIED_STAGES: readonly FunnelStage[] = [
  'number_verified',
  'verified_by_admin',
  'capturing',
]

/** A route-1 attempt that came back with nothing usable. */
const MSISDN_FAILURES = new Set(['msisdn_empty', 'number_mismatch', 'rejected'])

export type AttestStance =
  /** Already bound — the button must not appear at all. */
  | { kind: 'not_needed' }
  /** The automatic routes have not been exhausted. Offer it quietly, if at
   *  all: a proven binding is worth waiting for. */
  | { kind: 'premature' }
  /** No automatic route can complete. This is what attestation is for. */
  | { kind: 'offered'; because: 'msisdn_failed' | 'receiver_down' | 'both' }

export interface AttestInputs {
  stage: FunnelStage
  verifiedAt: string | null
  attempts: EnrolmentAttempt[]
  receiver: ReceiverStatus | undefined
}

export function attestStance({
  stage,
  verifiedAt,
  attempts,
  receiver,
}: AttestInputs): AttestStance {
  // A binding that exists is not re-asserted. Attesting over a proven one
  // would replace a fact with an opinion.
  if (verifiedAt !== null || VERIFIED_STAGES.includes(stage)) return { kind: 'not_needed' }

  const msisdnFailed = attempts.some(
    (attempt) => attempt.kind === 'msisdn_check' && MSISDN_FAILURES.has(attempt.outcome),
  )
  // `undefined` means the status has not loaded; absence of news is not news,
  // and treating it as "down" would open the hatch on a slow request.
  const receiverDown = receiver !== undefined && !receiver.enrolment_possible

  if (msisdnFailed && receiverDown) return { kind: 'offered', because: 'both' }
  if (msisdnFailed) return { kind: 'offered', because: 'msisdn_failed' }
  if (receiverDown) return { kind: 'offered', because: 'receiver_down' }

  // Route 1 has not failed and the callback is live: let them run. The admin
  // cannot trigger route 1 from here anyway — the phone does it — so pushing
  // attestation now would only be a way of not waiting.
  return { kind: 'premature' }
}

/** Why the hatch is open, as a catalogue key. */
export function stanceReasonKey(
  stance: Extract<AttestStance, { kind: 'offered' }>,
): 'attest.becauseMsisdn' | 'attest.becauseReceiver' | 'attest.becauseBoth' {
  switch (stance.because) {
    case 'msisdn_failed':
      return 'attest.becauseMsisdn'
    case 'receiver_down':
      return 'attest.becauseReceiver'
    case 'both':
      return 'attest.becauseBoth'
  }
}
