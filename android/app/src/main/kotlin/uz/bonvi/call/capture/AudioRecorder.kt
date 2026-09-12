package uz.bonvi.call.capture

import android.media.MediaRecorder
import uz.bonvi.call.domain.CaptureRoute
import java.io.File

/**
 * The thin seam over `MediaRecorder`.
 *
 * It exists for one reason: `MediaRecorderStrategy`'s interesting behaviour is
 * WHICH AUDIO SOURCE it settles on, and that logic must be testable without a
 * phone. With this interface the source-order rule is a unit test; without it,
 * the only way to check that `app_voice_recognition` and `app_mic` stay
 * distinguishable is to hold a Samsung.
 *
 * This is also the only file besides the OEM locators that may touch a media
 * API, and it lives under `capture/` for that reason
 * (`ArchitectureRulesTest`).
 */
interface AudioRecorder {
    /** Configure and start. Throws when the source is unavailable — which is
     *  the signal the strategy uses to try the next one down. */
    fun start(source: AudioSource, target: File)

    /** Stop and release. Returns the file if it holds usable audio. */
    fun stop(): File?

    /** Release without producing anything. Safe to call twice. */
    fun release()
}

/**
 * The audio sources, in descending order of what they capture (S1).
 *
 * ⚠️ `VOICE_CALL` was absent, with the note that it "is forbidden to non-system
 * apps, so trying it only costs a SecurityException per call". That is true at
 * targetSdk 29 and above — and **`legacy28` targets 28 exactly so it can ask**.
 * Leaving it out meant the flavour built to capture both parties never tried
 * the one source that carries both. CallSentry, which works on these handsets,
 * probes it first for the same reason.
 *
 * The cost of being wrong is one caught exception during
 * [MediaRecorderStrategy]'s probe, which already tries each source in turn and
 * moves on; the cost of leaving it out is every conversation recorded
 * half-deaf.
 */
enum class AudioSource(val platformValue: Int, val route: CaptureRoute) {

    /** Both parties. Granted only where the platform still allows it — which
     *  is what [preferenceOrder]'s flag decides, and what M0 measures. */
    VOICE_CALL(
        MediaRecorder.AudioSource.VOICE_CALL,
        CaptureRoute.APP_VOICE_CALL,
    ),
    /** Captures the OTHER PARTY on Samsung and some others. The reason this
     *  route has its own `capture_route` value: a fleet where every recording
     *  came from MIC is half-deaf, and the per-model table has to show it. */
    VOICE_RECOGNITION(
        MediaRecorder.AudioSource.VOICE_RECOGNITION,
        CaptureRoute.APP_VOICE_RECOGNITION,
    ),

    /** Mostly the near side only. */
    VOICE_COMMUNICATION(
        MediaRecorder.AudioSource.VOICE_COMMUNICATION,
        CaptureRoute.APP_VOICE_COMMUNICATION,
    ),

    /** Last resort. Nothing from the far side over Bluetooth or a headset. */
    MIC(
        MediaRecorder.AudioSource.MIC,
        CaptureRoute.APP_MIC,
    ),
    ;

    companion object {
        /**
         * The order to try, best first.
         *
         * `VOICE_RECOGNITION` is skipped where the platform no longer lets a
         * non-system app hear the far end through it — asked as a CAPABILITY,
         * never as a version check (`Capabilities.canUseVoiceRecognitionSource`).
         * Skipping it there is not a loss: it would return the near side only
         * and be reported as `app_voice_recognition`, which would make the M0
         * table say the far end was captured when it was not.
         */
        fun preferenceOrder(canUseVoiceRecognition: Boolean): List<AudioSource> =
            if (canUseVoiceRecognition) {
                listOf(VOICE_CALL, VOICE_RECOGNITION, VOICE_COMMUNICATION, MIC)
            } else {
                listOf(VOICE_CALL, VOICE_COMMUNICATION, MIC)
            }
    }
}

/**
 * The real recorder. AAC-LC in MP4 — SPEC §7.6's decided fallback container,
 * and what every supported handset can encode. The device transcodes to Opus
 * before upload (T73); recording straight to Opus is not available below
 * API 29 and the `legacy28` variant must run on API 26–28.
 */
class MediaRecorderAudioRecorder(
    private val recorderFactory: () -> MediaRecorder = { newPlatformRecorder() },
) : AudioRecorder {

    private var recorder: MediaRecorder? = null
    private var target: File? = null

    override fun start(source: AudioSource, target: File) {
        val recorder = recorderFactory()
        this.recorder = recorder
        this.target = target
        recorder.setAudioSource(source.platformValue)
        recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        recorder.setAudioChannels(CHANNELS)
        recorder.setAudioSamplingRate(SAMPLE_RATE_HZ)
        recorder.setAudioEncodingBitRate(BIT_RATE)
        recorder.setOutputFile(target.absolutePath)
        recorder.prepare()
        recorder.start()
    }

    override fun stop(): File? {
        val recorder = this.recorder ?: return null
        val file = this.target
        @Suppress("TooGenericExceptionCaught")
        try {
            recorder.stop()
        } catch (error: RuntimeException) {
            // Documented MediaRecorder behaviour: stop() throws when no frames
            // were written — a call so short the encoder never produced one.
            // That is `capture_returned_silence`, not a crash.
            release()
            return null
        }
        release()
        return file?.takeIf { it.exists() && it.length() > MIN_USABLE_BYTES }
    }

    override fun release() {
        recorder?.release()
        recorder = null
    }

    companion object {
        /** N17/N21: mono, 16 kHz. Speech, not music — and the storage budget in
         *  N18 is computed from these numbers. */
        const val CHANNELS = 1
        const val SAMPLE_RATE_HZ = 16_000
        const val BIT_RATE = 24_000

        /** Below this the file is a container header and no audio. */
        const val MIN_USABLE_BYTES = 2_048L

        // The MediaRecorder(Context) constructor arrived at API 31 and the
        // no-arg one is deprecated there. Both work on 26–34 and the difference
        // is a lint note, not behaviour, so there is no version branch here —
        // a branch would have to live in core/Capabilities.kt and would say
        // nothing about a capability.
        @Suppress("DEPRECATION")
        private fun newPlatformRecorder(): MediaRecorder = MediaRecorder()
    }
}
