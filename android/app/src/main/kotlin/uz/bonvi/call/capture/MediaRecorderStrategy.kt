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

    override fun start(target: File) {
        failure = null
        activeSource = null

        for (source in AudioSource.preferenceOrder(canUseVoiceRecognition())) {
            val candidate = recorderFactory()
            @Suppress("TooGenericExceptionCaught")
            try {
                candidate.start(source, target)
                recorder = candidate
                activeSource = source
                Timber.i("Recording on %s", source.route.wire)
                return
            } catch (error: Exception) {
                // Broad on purpose, and this is the specific failure it catches:
                // an audio source the OEM refuses (SecurityException), one
                // already held by the dialer (IllegalStateException), or an
                // encoder that will not prepare (IOException). Each is a signal
                // to try the next source down, not a reason to lose the call.
                Timber.w(error, "Audio source %s unavailable", source.route.wire)
                candidate.release()
            }
        }

        failure = AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE
    }

    override fun stop(): File? {
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
}
