package uz.bonvi.call.domain

/**
 * The call lifecycle (SPEC §7.5).
 *
 * ```
 *         ┌──────────── unregistered subscription ───────────► DISCARDED
 *         │                                                     (counter only)
 * IDLE ──► IDENTIFYING ──► RINGING/DIALING ──► ACTIVE ──► ENDED
 *                                 │                        │
 *                                 └── not answered ─────────┤
 *                                                           ▼
 *                                                    RECONCILING ──► METADATA_QUEUED
 *                                                           │              │
 *                                                           │              ▼
 *                                                           │        AUDIO_PENDING ──► AUDIO_QUEUED ──► COMPLETE
 *                                                           │              │
 *                                                           └──────────────┴──► NO_AUDIO(reason) ──► COMPLETE
 * ```
 *
 * The machine is **owned by the foreground service** and persisted to Room on
 * every transition, so a process death resumes rather than restarts. The
 * transition FUNCTION is here, pure, because the rules it encodes are the ones
 * that must be tested without a phone:
 *
 *  • [DISCARDED] is reached before any field is written. A call the privacy
 *    boundary rejected leaves a counter and nothing else — not a row with a
 *    number in it, not a queue entry.
 *  • an unanswered outgoing call reaches [METADATA_QUEUED] with no answer time
 *    and zero duration, and is never reported as a conversation (UC-09).
 *  • [NO_AUDIO] always carries a reason from the closed enum, and the call is
 *    still uploaded: **a call is never dropped because audio failed** (UC-14).
 */
enum class CallState {
    IDLE,

    /** Guard 1 runs here. Nothing has been written yet. */
    IDENTIFYING,

    RINGING,
    DIALING,
    ACTIVE,
    ENDED,

    /** Reading the device call log to correct direction, disposition, start
     *  time and duration (UC-13). Retried up to 15 minutes at 30 s intervals,
     *  because the log row appears after the call does. */
    RECONCILING,

    METADATA_QUEUED,
    AUDIO_PENDING,
    AUDIO_QUEUED,
    NO_AUDIO,
    COMPLETE,

    /** The privacy boundary said no. Terminal, and it holds no call data. */
    DISCARDED,
    ;

    val isTerminal: Boolean get() = this == COMPLETE || this == DISCARDED
}

/** What happened, as the service observes it. */
sealed interface CallEvent {
    /** A call appeared. Guard 1 has not run yet. */
    data object Detected : CallEvent

    /** Guard 1 said yes. Carries the proof, which is what unlocks capture. */
    data class Attributed(val capture: Decision.Capture) : CallEvent

    /** Guard 1 said no. */
    data class Rejected(val reason: RejectReason) : CallEvent

    data class Ringing(val direction: CallDirection) : CallEvent
    data object Answered : CallEvent
    data object Hungup : CallEvent

    data object ReconcileSucceeded : CallEvent

    /** The call log never produced a row. The call is still uploaded with what
     *  the device saw — SPEC §7.5's sweep reports the gap rather than inventing
     *  a row. */
    data object ReconcileGaveUp : CallEvent

    data object MetadataQueued : CallEvent

    /** Capture produced a file. */
    data object AudioCaptured : CallEvent

    /** Capture produced nothing, with a reason from the closed enum. */
    data class AudioMissing(val reason: AudioMissingReason) : CallEvent

    data object AudioQueued : CallEvent

    /** The server confirmed the checksum; local audio may now be deleted (N11). */
    data object UploadConfirmed : CallEvent
}

/** A transition the machine refused, kept as data so the service can log it
 *  rather than crash on it. An impossible event during a real call is a bug to
 *  find in the log, not a reason to lose the call. */
data class IllegalTransition(val from: CallState, val event: CallEvent)

data class TransitionResult(
    val state: CallState,
    val illegal: IllegalTransition? = null,
) {
    val changed: Boolean get() = illegal == null
}

/**
 * The transition rule. Pure: no Android, no Room, no clock.
 *
 * Unknown transitions return the CURRENT state plus an [IllegalTransition]
 * rather than throwing. During a real call an unexpected event is common — an
 * OEM that fires `ACTIVE` twice, a `Hungup` arriving after the log already
 * closed the call — and throwing there would take down the capture of a call
 * that is otherwise fine.
 */
object CallStateMachine {

    val INITIAL: CallState = CallState.IDLE

    @Suppress("CyclomaticComplexMethod")
    fun next(state: CallState, event: CallEvent): TransitionResult {
        val target: CallState? = when (state) {
            CallState.IDLE -> when (event) {
                is CallEvent.Detected -> CallState.IDENTIFYING
                else -> null
            }

            CallState.IDENTIFYING -> when (event) {
                // Fail closed, and terminal: nothing about this call is written.
                is CallEvent.Rejected -> CallState.DISCARDED
                is CallEvent.Attributed -> CallState.IDENTIFYING
                is CallEvent.Ringing -> when (event.direction) {
                    CallDirection.INCOMING -> CallState.RINGING
                    CallDirection.OUTGOING -> CallState.DIALING
                }
                // Some OEMs deliver an already-active call with no ringing edge.
                is CallEvent.Answered -> CallState.ACTIVE
                is CallEvent.Hungup -> CallState.ENDED
                else -> null
            }

            CallState.RINGING, CallState.DIALING -> when (event) {
                is CallEvent.Answered -> CallState.ACTIVE
                // Not answered. Still a call, still uploaded (UC-09).
                is CallEvent.Hungup -> CallState.ENDED
                is CallEvent.Rejected -> CallState.DISCARDED
                else -> null
            }

            CallState.ACTIVE -> when (event) {
                is CallEvent.Hungup -> CallState.ENDED
                // A duplicate Answered from a chatty OEM is not an error.
                is CallEvent.Answered -> CallState.ACTIVE
                else -> null
            }

            CallState.ENDED -> when (event) {
                is CallEvent.ReconcileSucceeded, is CallEvent.ReconcileGaveUp ->
                    CallState.RECONCILING
                else -> null
            }

            CallState.RECONCILING -> when (event) {
                is CallEvent.MetadataQueued -> CallState.METADATA_QUEUED
                // Audio can be decided before the metadata is queued on a fast
                // device; the machine does not force an order it cannot control.
                is CallEvent.AudioMissing -> CallState.NO_AUDIO
                is CallEvent.AudioCaptured -> CallState.AUDIO_PENDING
                else -> null
            }

            CallState.METADATA_QUEUED -> when (event) {
                is CallEvent.AudioCaptured -> CallState.AUDIO_PENDING
                is CallEvent.AudioMissing -> CallState.NO_AUDIO
                else -> null
            }

            CallState.AUDIO_PENDING -> when (event) {
                is CallEvent.AudioQueued -> CallState.AUDIO_QUEUED
                // The file vanished, the queue was full, retention expired.
                is CallEvent.AudioMissing -> CallState.NO_AUDIO
                else -> null
            }

            CallState.AUDIO_QUEUED -> when (event) {
                is CallEvent.UploadConfirmed -> CallState.COMPLETE
                is CallEvent.AudioMissing -> CallState.NO_AUDIO
                else -> null
            }

            CallState.NO_AUDIO -> when (event) {
                is CallEvent.MetadataQueued -> CallState.NO_AUDIO
                is CallEvent.UploadConfirmed -> CallState.COMPLETE
                else -> null
            }

            CallState.COMPLETE, CallState.DISCARDED -> null
        }

        return if (target == null) {
            TransitionResult(state, IllegalTransition(state, event))
        } else {
            TransitionResult(target)
        }
    }
}
