package uz.bonvi.call.capture

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import java.io.File

/**
 * The fallback route, and the reason T71a exists (SPEC §7.3, S1).
 *
 * One class, three audio sources, and **the source that succeeded is what the
 * route reports**. That is not tidiness: `VOICE_RECOGNITION` captures the far
 * end on Samsung and some others and `MIC` does not, so a fleet whose
 * recordings all came from `MIC` is half-deaf. A per-model table that recorded
 * only "audio: yes" could not tell that fleet from a healthy one, and M0's
 * whole job is to tell them apart.
 */
class MediaRecorderStrategyTest {

    /** Fails on every source in [failOn], succeeds otherwise. */
    private class FakeRecorder(
        private val failOn: Set<AudioSource>,
        private val produces: File?,
    ) : AudioRecorder {
        var startedWith: AudioSource? = null
            private set
        var released = false
            private set

        override fun start(source: AudioSource, target: File) {
            if (source in failOn) error("source unavailable: $source")
            startedWith = source
        }

        override fun stop(): File? = produces
        override fun release() { released = true }
    }

    private val file = File("call.m4a")

    private fun strategy(
        failOn: Set<AudioSource> = emptySet(),
        produces: File? = file,
        canUseVoiceRecognition: Boolean = true,
        microphoneAvailable: Boolean = true,
        recorders: MutableList<FakeRecorder> = mutableListOf(),
    ) = MediaRecorderStrategy(
        recorderFactory = { FakeRecorder(failOn, produces).also(recorders::add) },
        canUseVoiceRecognition = { canUseVoiceRecognition },
        microphoneAvailable = { microphoneAvailable },
    )

    @Test
    fun `the best available source is used and reported as its own route`() {
        val strategy = strategy()

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_RECOGNITION)
        assertThat(strategy.stop()).isEqualTo(file)
    }

    @Test
    fun `falling back to MIC is reported as app_mic, not as voice recognition`() {
        // The distinction the M0 table is built on. Reporting the preferred
        // source when the fallback ran would say the far end was captured when
        // it was not — the one lie this data set cannot afford.
        val strategy = strategy(failOn = setOf(AudioSource.VOICE_RECOGNITION, AudioSource.VOICE_COMMUNICATION))

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_MIC)
    }

    @Test
    fun `the middle source is reported as its own route too`() {
        val strategy = strategy(failOn = setOf(AudioSource.VOICE_RECOGNITION))

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_COMMUNICATION)
    }

    @Test
    fun `voice recognition is skipped where the platform will not give the far end`() {
        // Asked as a capability, never as a version. Skipping it is not a loss:
        // it would return the near side only and be REPORTED as
        // app_voice_recognition, which would corrupt the per-model table.
        val strategy = strategy(canUseVoiceRecognition = false)

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_COMMUNICATION)
    }

    @Test
    fun `isSupported is false without a working microphone, with a reason`() {
        // The branch that runs on most of the fleet
        // (CONVENTIONS-CLIENT.md §10 requires this test).
        val strategy = strategy(microphoneAvailable = false)

        assertThat(strategy.isSupported()).isFalse()
        assertThat(strategy.lastFailure()).isEqualTo(AudioMissingReason.NO_PERMISSION)
    }

    @Test
    fun `every source failing is a reason, not an exception`() {
        val strategy = strategy(failOn = AudioSource.entries.toSet())

        strategy.start(file)

        assertThat(strategy.lastFailure())
            .isEqualTo(AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE)
        assertThat(strategy.stop()).isNull()
    }

    @Test
    fun `a recorder that produced no file yields capture_returned_silence`() {
        val strategy = strategy(produces = null)

        strategy.start(file)
        val result = strategy.stop()

        assertThat(result).isNull()
        assertThat(strategy.lastFailure()).isEqualTo(AudioMissingReason.CAPTURE_RETURNED_SILENCE)
        // The route stays as the source that WAS recording: "app_mic produced
        // silence" is a different fact from "no route was available".
        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_RECOGNITION)
    }

    @Test
    fun `a failed source releases its recorder rather than leaking the microphone`() {
        // A leaked MediaRecorder holds the mic and the NEXT call captures
        // nothing — a failure that shows up one call later than its cause.
        val recorders = mutableListOf<FakeRecorder>()
        val strategy = strategy(failOn = setOf(AudioSource.VOICE_RECOGNITION), recorders = recorders)

        strategy.start(file)

        assertThat(recorders.first().released).isTrue()
    }

    @Test
    fun `the source order is best-first and never tries VOICE_CALL`() {
        // VOICE_CALL is the best source and is forbidden to non-system apps, so
        // trying it costs a SecurityException per call and gains nothing.
        assertThat(AudioSource.preferenceOrder(canUseVoiceRecognition = true))
            .containsExactly(
                AudioSource.VOICE_RECOGNITION,
                AudioSource.VOICE_COMMUNICATION,
                AudioSource.MIC,
            )
            .inOrder()
        assertThat(AudioSource.entries.map { it.name }).doesNotContain("VOICE_CALL")
    }

    @Test
    fun `each source maps to its own capture_route value`() {
        assertThat(AudioSource.entries.map { it.route }).containsNoDuplicates()
    }
}
