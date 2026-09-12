package uz.bonvi.call.capture

import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import java.io.File

/**
 * The capture seam (SPEC §7.3, CONVENTIONS-CLIENT.md §6, T71a).
 *
 * `isSupported()` / `start(File)` / `stop(): File?` are adopted UNCHANGED from
 * `../CallSentry/service/recording/RecordingStrategy.kt`. Two additions, both
 * because the panel and the M0 baseline depend on them:
 *
 *  - [route] — which mechanism produced this file, recorded per call. It is a
 *    **getter, not a constant**: `MediaRecorderStrategy` is one class that
 *    tries three audio sources, and the source that succeeded is what it
 *    reports, so `app_voice_recognition` and `app_mic` stay distinguishable in
 *    the data without being separate classes. S1 is the reason that matters —
 *    `VOICE_RECOGNITION` captures the far end on Samsung and some others,
 *    `MIC` does not, and a per-model table that collapsed them into "audio:
 *    yes/no" could not tell a working fleet from a half-deaf one.
 *  - [lastFailure] — why it produced nothing, from the CLOSED enum. Never free
 *    text: the gap report groups by this field.
 *
 * A strategy that produces no file is not an error. The call is uploaded
 * anyway, with the reason (UC-14): **a call is never dropped because audio
 * failed.**
 */
interface RecordingStrategy {

    /**
     * The route this strategy represents *for the attempt that just finished*.
     * Read after [stop]; before then it is the strategy's nominal route.
     */
    val route: CaptureRoute

    /**
     * Can this strategy run on THIS device, right now?
     *
     * CONVENTIONS-CLIENT.md §10 requires every implementation to have a test
     * for the FALSE branch, because on most of the fleet that is the branch
     * that runs. When it returns false it should also set [lastFailure], or the
     * router has to guess why.
     */
    fun isSupported(): Boolean

    /**
     * Begin capturing into [target].
     *
     * Implementations must not throw: a capture failure is DATA (a reason on a
     * call that is uploaded regardless), and an exception here would propagate
     * into the call state machine and lose the call itself.
     */
    fun start(target: File)

    /** The produced file, or null. Null is a normal outcome. */
    fun stop(): File?

    /** Set when [stop] returned null or [isSupported] returned false. */
    fun lastFailure(): AudioMissingReason?

    /**
     * True for a strategy that records nothing itself and only LOOKS for a
     * file at [stop] — the OEM harvest. The router stops the live recorders
     * first, because a microphone left running while a post-hoc strategy
     * polls for the handset's file records the employee after the call has
     * ended (six seconds of their voice on the first real handset,
     * 2026-09-12).
     */
    val postHoc: Boolean get() = false
}
