package uz.bonvi.call.capture

import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * The preferred route: harvest the file the handset's own recorder wrote
 * (SPEC §7.3, S1).
 *
 * It is **post-hoc**. There is nothing to start — the OEM recorder is running
 * or it is not, and the app cannot switch it on. [start] only fixes the window
 * this call is allowed to look in; [stop] asks the locator for a file.
 *
 * ⚠️ **The privacy boundary passes through this class** (CONVENTIONS.md §8.2,
 * SPEC §7.4). It is constructed with a [Decision.Capture] — the PROOF that this
 * call was placed on the registered subscription — and hands that proof to
 * [OemRecordingLocator.locate]. There is no constructor and no method that
 * accepts a raw number or a call id, so a caller that has not passed
 * `PrivacyBoundary.evaluate()` cannot reach the folder scan at all. That
 * signature is the enforcement; do not add a weaker one.
 *
 * ═══ Why this is the route that matters on this fleet ═════════════════════
 * Measured on a Xiaomi 13 Lite (Android 13) on 2026-09-12: Android's
 * concurrent-capture policy SILENCES an ordinary app's microphone for the whole
 * time telephony is in `MODE_IN_CALL` (`dumpsys audio`: every one of our
 * `VOICE_COMMUNICATION` sessions was flagged `silenced` until hang-up, and
 * ffmpeg on the resulting file showed 0 s–32 s of digital silence followed by
 * six seconds of the employee talking AFTER the call ended). `VOICE_CALL` is
 * refused to any app without `CAPTURE_AUDIO_OUTPUT`, which no third-party app
 * holds. So on Android 10+ the app's own recorder cannot capture EITHER voice
 * during a call — the handset's own recorder is the only source of a
 * conversation, and Moi Zvonki, which works on the same phone, never opens the
 * microphone there at all: it reads this same folder.
 */
class OemHarvestStrategy(
    private val capture: Decision.Capture,
    private val locator: OemRecordingLocator,
    /** `Capabilities` reports whether the OEM recorder is even reachable on
     *  this handset; the checker reports whether the user has it switched on
     *  (UC-03's `oem_recorder` capability). */
    private val recorderReachable: () -> Boolean,
    /** Injected so tests do not actually wait. The real sleeper blocks the
     *  IO thread `stop()` already runs on -- see [stop]. */
    private val sleeper: (Long) -> Unit = { Thread.sleep(it) },
    /** Wall clock, injected so the stop-time bound on the window is testable. */
    private val clock: () -> Long = { Clock.epochMillis() },
) : RecordingStrategy {

    private var failure: AudioMissingReason? = null

    override val route: CaptureRoute = CaptureRoute.OEM_FILE_HARVEST

    /** Nothing to stop: [stop] only polls for the handset's file. */
    override val postHoc: Boolean = true

    override fun isSupported(): Boolean {
        if (!recorderReachable()) {
            failure = AudioMissingReason.OEM_RECORDER_OFF
            return false
        }
        return true
    }

    /**
     * Nothing starts. The parameter is ignored on purpose: this strategy never
     * writes a file, it finds one, and the OEM's files are opened read-only and
     * never moved, modified or deleted (CONVENTIONS.md §8.3).
     */
    override fun start(target: File) {
        failure = null
    }

    override fun stop(): File? {
        // ═══ The window's upper end is fixed HERE, at the stop ═══════════════
        // The decision was made while the call was still ringing, so its
        // `endedAtEpochMillis` is the detector's provisional `Long.MAX_VALUE`
        // (CaptureCoordinator.prepare). The call has ended NOW, and now is the
        // only honest upper bound: `[answeredAt - 5 s, now + 120 s]` is a
        // window this call owns, and a later call's file can never fall in it.
        // Left unbounded it did worse than widen the boundary -- it overflowed
        // and matched nothing (see OemRecordingMatch.windowFor).
        val bounded = capture.copy(
            endedAtEpochMillis = minOf(capture.endedAtEpochMillis, clock()),
        )

        // ⚠️ POLL, do not scan once. The handset's own recorder closes its
        // file AT or a few seconds AFTER the call ends (measured at hang-up
        // and at +6..+7 s on two Xiaomi handsets, 2026-09-12), so a single
        // scan can look too early. Polling does NOT widen the privacy
        // boundary: the window is fixed above, so a later scan can only ever
        // match THIS call's file.
        //
        // And a match is taken only once its SIZE HAS SETTLED across two
        // consecutive scans. The OEM writer grows the file progressively and
        // finalises it at hang-up; a file taken on the scan that first sees it
        // can be the one still being written, and a truncated both-voices
        // recording is the one failure the panel cannot tell from a short call.
        var seen: File? = null
        var seenBytes = -1L
        repeat(OemRecordingLocator.RETRY_COUNT) { attempt ->
            val file = locator.locate(bounded)
            if (file != null) {
                val bytes = file.length()
                if (file == seen && bytes == seenBytes) {
                    failure = null
                    return file
                }
                seen = file
                seenBytes = bytes
            }
            if (attempt < OemRecordingLocator.RETRY_COUNT - 1) {
                sleeper(OemRecordingLocator.RETRY_INTERVAL_MS)
            }
        }

        val last = seen
        if (last != null) {
            // Matched only on the final scan, with no chance to confirm the
            // size had settled. Ten seconds after hang-up the OEM writer has
            // closed the file on every handset measured so far; taking it is
            // better than discarding a both-voices recording for the lack of
            // one more second.
            failure = null
            Timber.i("OEM recording taken on the last scan without a settled-size check")
            return last
        }

        // The window matched nothing, even after waiting. This is the boundary
        // REFUSING, not a bug: an unmatched recording in that folder is the
        // employee's private call, discarded on the device rather than
        // uploaded and sorted out server-side. The app's own mic recording, if
        // it took, is the fallback the router picks instead.
        failure = AudioMissingReason.ATTRIBUTION_FAILED
        Timber.i(
            "No OEM recording matched this call's window after %d attempts",
            OemRecordingLocator.RETRY_COUNT,
        )
        return null
    }

    override fun lastFailure(): AudioMissingReason? = failure
}
