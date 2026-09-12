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

    /** Fails on every source in [failOn], succeeds otherwise. A source in
     *  [forbidOn] throws SecurityException (barred, never worth a retry). */
    private class FakeRecorder(
        private val failOn: Set<AudioSource>,
        private val produces: File?,
        private val forbidOn: Set<AudioSource> = emptySet(),
    ) : AudioRecorder {
        var startedWith: AudioSource? = null
            private set
        var released = false
            private set

        override fun start(source: AudioSource, target: File) {
            if (source in forbidOn) throw SecurityException("source forbidden: $source")
            if (source in failOn) error("source unavailable: $source")
            startedWith = source
        }

        override fun stop(): File? = produces
        override fun release() { released = true }
    }

    private val file = File("call.m4a")

    /** How many times the connect-window sleep was invoked in the last run. */
    private var sleeps = 0

    private fun strategy(
        failOn: Set<AudioSource> = emptySet(),
        forbidOn: Set<AudioSource> = emptySet(),
        produces: File? = file,
        canUseVoiceRecognition: Boolean = true,
        microphoneAvailable: Boolean = true,
        recorders: MutableList<FakeRecorder> = mutableListOf(),
    ): MediaRecorderStrategy {
        sleeps = 0
        return MediaRecorderStrategy(
            recorderFactory = { FakeRecorder(failOn, produces, forbidOn).also(recorders::add) },
            canUseVoiceRecognition = { canUseVoiceRecognition },
            microphoneAvailable = { microphoneAvailable },
            // No real waiting in a unit test.
            sleeper = { sleeps++ },
        )
    }

    @Test
    fun `the best available source is used and reported as its own route`() {
        // On a handset that grants it, VOICE_CALL is the best rung and the one
        // that carries both parties. Everything below is a degradation and the
        // route says which, because that is what the M0 table is built on.
        val strategy = strategy()

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_CALL)
        assertThat(strategy.stop()).isEqualTo(file)
    }

    @Test
    fun `falling back to MIC is reported as app_mic, not as voice recognition`() {
        // The distinction the M0 table is built on. Reporting the preferred
        // source when the fallback ran would say the far end was captured when
        // it was not — the one lie this data set cannot afford.
        val strategy = strategy(
            failOn = setOf(
                AudioSource.VOICE_CALL,
                AudioSource.VOICE_RECOGNITION,
                AudioSource.VOICE_COMMUNICATION,
            ),
        )

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_MIC)
    }

    @Test
    fun `the middle source is reported as its own route too`() {
        val strategy = strategy(
            failOn = setOf(AudioSource.VOICE_CALL, AudioSource.VOICE_RECOGNITION),
        )

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_COMMUNICATION)
    }

    @Test
    fun `voice recognition is skipped where the platform will not give the far end`() {
        // Asked as a capability, never as a version. Skipping it is not a loss:
        // it would return the near side only and be REPORTED as
        // app_voice_recognition, which would corrupt the per-model table.
        val strategy = strategy(
            failOn = setOf(AudioSource.VOICE_CALL),
            canUseVoiceRecognition = false,
        )

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
        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_CALL)
    }

    @Test
    fun `a failed source releases its recorder rather than leaking the microphone`() {
        // A leaked MediaRecorder holds the mic and the NEXT call captures
        // nothing — a failure that shows up one call later than its cause.
        val recorders = mutableListOf<FakeRecorder>()
        val strategy = strategy(failOn = setOf(AudioSource.VOICE_CALL), recorders = recorders)

        strategy.start(file)

        assertThat(recorders.first().released).isTrue()
    }

    @Test
    fun `the source order is best-first and VOICE_CALL is tried first`() {
        // ⚠️ The inverse of the test that stood here, which asserted VOICE_CALL
        // was never tried "because it is forbidden to non-system apps". That is
        // true from targetSdk 29 — and the `legacy28` flavour targets 28
        // precisely so it can ask. The old rule meant the one build made to
        // capture both parties never tried the one source that carries both.
        // CallSentry, which works on these handsets, probes it first.
        //
        // Being wrong costs one caught exception inside the probe below, which
        // already walks the list; being right is the difference between a
        // recording of a conversation and a recording of one person talking.
        assertThat(AudioSource.preferenceOrder(canUseVoiceRecognition = true))
            .containsExactly(
                AudioSource.VOICE_CALL,
                AudioSource.VOICE_RECOGNITION,
                AudioSource.VOICE_COMMUNICATION,
                AudioSource.MIC,
            )
            .inOrder()
        assertThat(AudioSource.preferenceOrder(canUseVoiceRecognition = false))
            .containsExactly(
                AudioSource.VOICE_CALL,
                AudioSource.VOICE_COMMUNICATION,
                AudioSource.MIC,
            )
            .inOrder()
    }

    @Test
    fun `VOICE_CALL is reported as its own route, never as another`() {
        // The M0 table's whole purpose is to say which handsets got the far
        // end. Filing a VOICE_CALL recording under `app_voice_recognition`
        // would make it claim a source captured something it cannot.
        assertThat(AudioSource.VOICE_CALL.route)
            .isEqualTo(uz.bonvi.call.domain.CaptureRoute.APP_VOICE_CALL)
    }

    @Test
    fun `each source maps to its own capture_route value`() {
        assertThat(AudioSource.entries.map { it.route }).containsNoDuplicates()
    }

    @Test
    fun `VOICE_CALL is retried through the ring and wins once the line connects`() {
        // The whole reason this fleet shipped app_voice_communication instead
        // of app_voice_call: on an outgoing call VOICE_CALL is refused while the
        // line rings, and a single attempt settled for the near side. It has to
        // be waited for. Here it fails the first three attempts (still ringing)
        // and then connects.
        var attempts = 0
        val strategy = MediaRecorderStrategy(
            recorderFactory = {
                object : AudioRecorder {
                    override fun start(source: AudioSource, target: File) {
                        if (source == AudioSource.VOICE_CALL && attempts++ < 3) {
                            error("still ringing")
                        }
                        if (source != AudioSource.VOICE_CALL) error("not this one")
                    }
                    override fun stop(): File = file
                    override fun release() {}
                }
            },
            canUseVoiceRecognition = { true },
            microphoneAvailable = { true },
            sleeper = { sleeps++ },
        )

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_CALL)
        assertThat(attempts).isEqualTo(4) // three rings, then connected
        assertThat(sleeps).isEqualTo(3) // one wait between each failed attempt
    }

    @Test
    fun `a forbidden VOICE_CALL is not retried and the near side is taken at once`() {
        // A handset that BARS VOICE_CALL to apps (SecurityException) can never
        // be waited into working, and blocking the connect window would only
        // delay the near-side recording that is the honest fallback there.
        val strategy = strategy(forbidOn = setOf(AudioSource.VOICE_CALL))

        strategy.start(file)

        assertThat(strategy.route).isEqualTo(CaptureRoute.APP_VOICE_RECOGNITION)
        assertThat(sleeps).isEqualTo(0) // no waiting on a source that is barred
    }
}
