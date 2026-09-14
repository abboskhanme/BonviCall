/**
 * The closed server enums, rendered in Uzbek.
 *
 * Every map here is `Record<<enum>, MessageKey>` over a type from
 * `types.gen.ts`. That is the whole point: when the server adds a value to
 * `AudioMissingReason`, `make types` widens the union and these maps stop
 * compiling, so a new reason cannot reach the screen as a blank cell or a raw
 * snake_case identifier. A `Partial<>` or a `??` fallback here would turn that
 * compile error back into a silent gap, which is exactly the question this page
 * exists to answer (UC-14).
 *
 * The Uzbek text itself lives in `shared/i18n/uz.json`; only keys appear here
 * (CONVENTIONS.md §14).
 */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

export type Call = components['schemas']['CallResponse']
export type CallAudioSummary = components['schemas']['CallAudioSummary']
export type CaptureRoute = components['schemas']['CaptureRoute']
export type CallDirection = components['schemas']['CallDirection']
export type CallDisposition = components['schemas']['CallDisposition']
export type CallType = components['schemas']['CallType']
export type CallSource = components['schemas']['CallSource']
export type AudioMissingReason = components['schemas']['AudioMissingReason']

export const DIRECTION_LABEL: Record<CallDirection, MessageKey> = {
  incoming: 'calls.direction.incoming',
  outgoing: 'calls.direction.outgoing',
}

export const DISPOSITION_LABEL: Record<CallDisposition, MessageKey> = {
  answered: 'calls.disposition.answered',
  missed: 'calls.disposition.missed',
  rejected: 'calls.disposition.rejected',
  no_answer: 'calls.disposition.no_answer',
}

export const CALL_TYPE_LABEL: Record<CallType, MessageKey> = {
  internal: 'calls.type.internal',
  external: 'calls.type.external',
  unknown: 'calls.type.unknown',
}

/**
 * The same enum MINUS `unknown`, for the call list's "Turi" filter only.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **This subset is deliberate and is not a bug to be "fixed" back.** The client
 * asked for the filter to offer Ichki and Tashqi and nothing else.
 *
 * `unknown` remains a real, stored value that rows genuinely carry: SPEC §10.2
 * makes it the mandatory default for a call the line directory cannot classify,
 * because BonviZvonki defaulted to `external` instead and mislabelled 82 calls
 * out of 98. It is still rendered — the badge on the call detail page reads it
 * out of `CALL_TYPE_LABEL` above, which keeps all three entries — and the
 * server still accepts `call_type=unknown` on the wire. Only this one filter's
 * option list is shorter.
 *
 * It is a separate map rather than a filtered `CALL_TYPE_LABEL` because
 * `EnumFilter` derives its options from exactly one map and says why: "a value
 * the server adds appears in both at once, or in neither". Narrowing a filter
 * by hand costs that guarantee for this filter, so the narrowing is written
 * down in one place with its reason attached. `Record<Exclude<…>>` still means
 * a new CallType value breaks the build here rather than going unnoticed.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export const CALL_TYPE_FILTER_LABEL: Record<Exclude<CallType, 'unknown'>, MessageKey> = {
  internal: 'calls.type.internal',
  external: 'calls.type.external',
}

export const SOURCE_LABEL: Record<CallSource, MessageKey> = {
  live_capture: 'calls.source.live_capture',
  call_log_recovery: 'calls.source.call_log_recovery',
  provider: 'calls.source.provider',
}

/**
 * Why a call has no recording (SPEC §3.9, N5).
 *
 * The database CHECK guarantees a reason is present whenever `has_audio` is
 * false, so the list renders the sentence rather than an empty cell: "why is
 * there no recording" is the question the panel is for.
 */
export const AUDIO_MISSING_REASON_LABEL: Record<AudioMissingReason, MessageKey> = {
  pending_upload: 'calls.noAudioReason.pending_upload',
  not_expected: 'calls.noAudioReason.not_expected',
  recording_route_unavailable: 'calls.noAudioReason.recording_route_unavailable',
  oem_recorder_off: 'calls.noAudioReason.oem_recorder_off',
  no_permission: 'calls.noAudioReason.no_permission',
  capture_returned_silence: 'calls.noAudioReason.capture_returned_silence',
  app_not_running: 'calls.noAudioReason.app_not_running',
  upload_expired: 'calls.noAudioReason.upload_expired',
  queue_space_exhausted: 'calls.noAudioReason.queue_space_exhausted',
  attribution_failed: 'calls.noAudioReason.attribution_failed',
}

export type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'accent'

export const DISPOSITION_TONE: Record<CallDisposition, BadgeTone> = {
  answered: 'good',
  missed: 'bad',
  rejected: 'warn',
  no_answer: 'warn',
}

/**
 * How alarming an absent recording is.
 *
 * `pending_upload` and `not_expected` are neutral on purpose — they are the two
 * reasons the gap report excludes from its denominator (SPEC §3.9), because
 * neither one is a capture failure. Colouring them red would make a healthy
 * fleet look broken for the ninety seconds between a call ending and its audio
 * arriving.
 */
export const AUDIO_MISSING_REASON_TONE: Record<AudioMissingReason, BadgeTone> = {
  pending_upload: 'neutral',
  not_expected: 'neutral',
  recording_route_unavailable: 'bad',
  oem_recorder_off: 'warn',
  no_permission: 'warn',
  capture_returned_silence: 'bad',
  app_not_running: 'warn',
  upload_expired: 'bad',
  queue_space_exhausted: 'bad',
  attribution_failed: 'bad',
}

export const CAPTURE_ROUTE_LABEL: Record<CaptureRoute, MessageKey> = {
  oem_file_harvest: 'calls.captureRoute.oem_file_harvest',
  app_voice_call: 'calls.captureRoute.app_voice_call',
  app_voice_recognition: 'calls.captureRoute.app_voice_recognition',
  app_voice_communication: 'calls.captureRoute.app_voice_communication',
  app_mic: 'calls.captureRoute.app_mic',
  none: 'calls.captureRoute.none',
}

/**
 * Why there is no recording — and these are NOT the same answer.
 *
 * ══════════════════════════════════════════════════════════════════════════
 * `audio.available === false` covers two situations that look identical on a
 * screen and mean opposite things, and **only one of them is somebody's
 * fault**:
 *
 *   `expired`  the recording existed and the 12-month retention job deleted
 *              it (SPEC §3.11, N19). The system worked. Nobody did anything
 *              wrong. Playback would answer 410 `audio_expired`.
 *
 *   `missing`  the recording never existed. This is a capture failure, and it
 *              is what the gap report counts (UC-23).
 *
 * Collapsing them would put normal retention into the gap report's numerator.
 * That report is how Bonvi decides whether a handset or a person has a
 * problem, so conflating the two points at the wrong person. The two states
 * therefore carry different words, different tones, and a test each.
 *
 * They are mutually exclusive by construction: the `audio_reason_present`
 * CHECK makes a call with audio carry no missing reason, so a row that was
 * later expired by retention has `expired_at` set and `audio_missing_reason`
 * NULL. `expired` is still checked first, because "it existed" is the stronger
 * fact about a recording than "it is not here now".
 * ══════════════════════════════════════════════════════════════════════════
 */
export type AudioState =
  | { kind: 'available' }
  | { kind: 'expired'; expiredAt: string }
  | { kind: 'missing'; reason: AudioMissingReason }
  | { kind: 'unknown' }

export function audioState(audio: CallAudioSummary): AudioState {
  if (audio.available) return { kind: 'available' }
  if (audio.expired_at) return { kind: 'expired', expiredAt: audio.expired_at }
  if (audio.audio_missing_reason) {
    return { kind: 'missing', reason: audio.audio_missing_reason }
  }
  // Unreachable while the CHECK constraint holds. Written out rather than
  // assumed away: the panel must not render a blank cell for a row somebody
  // has edited by hand, because a blank cell is the one answer this column
  // may never give.
  return { kind: 'unknown' }
}

/** The short label for the audio column. */
export function audioStateLabel(state: AudioState): MessageKey {
  switch (state.kind) {
    case 'available':
      return 'calls.audio.present'
    case 'expired':
      return 'calls.audio.expired'
    case 'missing':
      return AUDIO_MISSING_REASON_LABEL[state.reason]
    case 'unknown':
      return 'calls.noAudioReasonUnknown'
  }
}

/**
 * `expired` is deliberately neutral, not red: retention deleting a year-old
 * recording is the policy doing its job, and colouring it as a failure trains
 * people to ignore the colour that means an actual failure.
 */
export function audioStateTone(state: AudioState): BadgeTone {
  switch (state.kind) {
    case 'available':
      return 'good'
    case 'expired':
      return 'neutral'
    case 'missing':
      return AUDIO_MISSING_REASON_TONE[state.reason]
    case 'unknown':
      return 'neutral'
  }
}
