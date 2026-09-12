package uz.bonvi.call.capture

import timber.log.Timber
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import java.io.File

/**
 * The fallback route: the app records for itself (SPEC §7.3, T71a).
 *
 * One class, three audio sources, tried in descending order of what they
 * actually capture. **The source that succeeded is what [route] reports**, so
 * `app_voice_recognition` and `app_mic` remain separate values in the data even
 * though they are one class — which is the whole point of T71a's route
 * reporting. S1 is why it matters: `VOICE_RECOGNITION` captures the far end on
 * Samsung and some others and `MIC` does not, so a fleet whose recordings all
 * came from `MIC` is half-deaf, and a per-model table that said only "audio:
 * yes" could not tell that from a healthy one.
 *
 * This is the route that will actually run on most of the fleet
 * (CONVENTIONS-CLIENT.md §10), so the `isSupported() == false` branch and the
 * source-order rule both have tests.
 */
class MediaRecorderStrategy(
    private val recorderFactory: () -> AudioRecorder,
    /** `Capabilities.canUseVoiceRecognitionSource()`, injected so the order is
     *  testable. A capability, never a version (CONVENTIONS-CLIENT.md §7). */
    private val canUseVoiceRecognition: () -> Boolean,
    /** Whether RECORD_AUDIO is actually granted AND working. `granted_not_
     *  working` is a real state (UC-03), so this asks the checker rather than
     *  the permission. */
    private val microphoneAvailable: () -> Boolean,
    /** Injected so tests do not wait through the connect window. The real
     *  sleeper blocks the capture coroutine (the live call-state path, which
     *  has no broadcast budget), and `stopRequested` bails it out early. */
    private val sleeper: (Long) -> Unit = { Thread.sleep(it) },
) : RecordingStrategy {

    private var recorder: AudioRecorder? = null
    private var activeSource: AudioSource? = null
    private var failure: AudioMissingReason? = null

    /**
     * The source that produced the last file — not a constant.
     *
     * Before a successful [start] it reports [CaptureRoute.APP_MIC], the
     * pessimistic answer: claiming `app_voice_recognition` before knowing which
     * source took would overstate what was captured, and overstating capture is
     * the failure mode the whole gap report exists to catch.
     */
    override val route: CaptureRoute
        get() = activeSource?.route ?: CaptureRoute.APP_MIC

    override fun isSupported(): Boolean {
        if (!microphoneAvailable()) {
            failure = AudioMissingReason.NO_PERMISSION
            return false
        }
        return true
    }

    @Volatile
    private var stopRequested = false

    override fun start(target: File) {
        failure = null
        activeSource = null
        stopRequested = false

        val order = AudioSource.preferenceOrder(canUseVoiceRecognition())

        // ═══ Why VOICE_CALL is RETRIED, and nothing else is ═══════════════════
        // VOICE_CALL is the one source that carries BOTH parties, and it only
        // becomes available once the call is CONNECTED. On an outgoing call the
        // platform reports OFFHOOK at dialing, so we are started while the line
        // is still ringing: a single attempt throws, we settle for the near
        // side, and the customer's half of the conversation — the entire point
        // of this product — is lost for the whole call.
        //
        // Moi Zvonki, which DOES capture both sides on these handsets, does not
        // harvest the OEM folder (MIUI bars other apps from it, measured
        // 2026-09-12). It records VOICE_CALL itself and RETRIES until the line
        // is up. So do we: poll VOICE_CALL across the ring-to-answer window,
        // and only where the platform says it is UNAVAILABLE (still ringing),
        // never where it is FORBIDDEN (a handset that bars the source to apps —
        // waiting cannot change that, and blocking would only delay the near
        // side).
        val callSource = order.firstOrNull { it == AudioSource.VOICE_CALL }
        if (callSource != null) {
            for (attempt in 0 until CONNECT_RETRIES) {
                if (stopRequested) return
                when (tryStart(callSource, target)) {
                    StartResult.STARTED -> return
                    StartResult.FORBIDDEN -> break
                    StartResult.UNAVAILABLE -> sleeper(CONNECT_RETRY_INTERVAL_MS)
                }
            }
        }

        // The line never came up on VOICE_CALL (still ringing at the window's
        // end, or it is forbidden here). Take the best NEAR-SIDE source now — a
        // near-side recording is better than none, and it is where most of the
        // fleet's audio comes from regardless.
        if (stopRequested) return
        for (source in order.filter { it != AudioSource.VOICE_CALL }) {
            if (tryStart(source, target) == StartResult.STARTED) return
        }

        failure = AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE
    }

    private enum class StartResult { STARTED, FORBIDDEN, UNAVAILABLE }

    private fun tryStart(source: AudioSource, target: File): StartResult {
        val candidate = recorderFactory()
        return try {
            candidate.start(source, target)
            recorder = candidate
            activeSource = source
            Timber.i("Recording on %s", source.route.wire)
            StartResult.STARTED
        } catch (error: SecurityException) {
            // The handset bars this source to a non-system app. Permanent —
            // retrying it only delays the fallback.
            Timber.w(error, "Audio source %s forbidden", source.route.wire)
            candidate.release()
            StartResult.FORBIDDEN
        } catch (@Suppress("TooGenericExceptionCaught") error: Exception) {
            // Not ready: the source is held by the dialer, the line is still
            // ringing, or the encoder will not prepare yet. For VOICE_CALL this
            // is the ring — worth waiting through; for a near-side source it is
            // a signal to try the next one down. Either way, never a lost call.
            Timber.w(error, "Audio source %s unavailable", source.route.wire)
            candidate.release()
            StartResult.UNAVAILABLE
        }
    }

    override fun stop(): File? {
        // Bail a start() that is still polling VOICE_CALL through the ring.
        stopRequested = true
        val active = recorder ?: run {
            // start() never got a source. failure is already set.
            failure = failure ?: AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE
            return null
        }
        val file = active.stop()
        recorder = null
        if (file == null) {
            failure = AudioMissingReason.CAPTURE_RETURNED_SILENCE
            // The route stays as the source that was recording: knowing that
            // app_mic produced silence is a different fact from no route being
            // available at all, and the gap report distinguishes them.
        }
        return file
    }

    override fun lastFailure(): AudioMissingReason? = failure

    private companion object {
        /**
         * How long to wait for VOICE_CALL to come up before settling for the
         * near side. `CONNECT_RETRIES * CONNECT_RETRY_INTERVAL_MS` is the
         * ring-to-answer window it spans — an outbound call the customer
         * answers inside this window is recorded in BOTH voices; one that rings
         * longer falls to the near side. 20 s covers ordinary answer times
         * without waiting out a call that has gone to voicemail. It runs on the
         * live call-state path (no broadcast budget) and `stopRequested` cuts
         * it short the instant the call ends.
         *
         * 15, not more: on a handset that bars VOICE_CALL through a non-
         * SecurityException path this is also the near-side recording's worst-
         * case delay, so the window is kept to what an ordinary answer needs.
         */
        const val CONNECT_RETRIES = 15
        const val CONNECT_RETRY_INTERVAL_MS = 1_000L
    }
}
