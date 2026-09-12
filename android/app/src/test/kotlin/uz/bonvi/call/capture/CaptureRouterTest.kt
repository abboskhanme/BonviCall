package uz.bonvi.call.capture

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * The capture seam (T71a).
 *
 * Three properties are pinned here, and the M0 per-model table is unreadable
 * without all three:
 *
 *  1. every SUPPORTED strategy is started, because you cannot know until the
 *     call has ended whether the handset's own recorder produced anything;
 *  2. the winner is the first in PREFERENCE ORDER that produced a file, not the
 *     first that started;
 *  3. every attempt is REPORTED — "the OEM route was tried and found nothing"
 *     is a different fact from "the OEM route was never available", and the gap
 *     report has to tell them apart.
 */
class CaptureRouterTest {

    private class FakeStrategy(
        private val nominalRoute: CaptureRoute,
        private val supported: Boolean = true,
        private val produces: File? = null,
        private val failure: AudioMissingReason? = null,
        private val throwOnStart: Boolean = false,
    ) : RecordingStrategy {
        var started = false
            private set
        var stopped = false
            private set

        override val route: CaptureRoute get() = nominalRoute
        override fun isSupported(): Boolean = supported
        override fun start(target: File) {
            if (throwOnStart) error("recorder busy")
            started = true
        }
        override fun stop(): File? {
            stopped = true
            return produces
        }
        override fun lastFailure(): AudioMissingReason? = failure
    }

    private val oemFile = File("oem.m4a")
    private val appFile = File("app.m4a")

    private fun router(vararg strategies: RecordingStrategy) = CaptureRouter(strategies.toList())

    private fun CaptureRouter.runCall(): CaptureRouter.Outcome {
        start { File("${it.route.wire}.m4a") }
        return stop()
    }

    @Test
    fun `both routes run and the preferred one wins`() {
        // The app recorder runs as INSURANCE and is discarded when the OEM file
        // exists. That is CallSentry's behaviour and S1 confirmed the ordering.
        val oem = FakeStrategy(CaptureRoute.OEM_FILE_HARVEST, produces = oemFile)
        val app = FakeStrategy(CaptureRoute.APP_VOICE_RECOGNITION, produces = appFile)

        val outcome = router(oem, app).runCall()

        assertThat(oem.started).isTrue()
        assertThat(app.started).isTrue() // insurance, not dead code
        assertThat(outcome.file).isEqualTo(oemFile)
        assertThat(outcome.route).isEqualTo(CaptureRoute.OEM_FILE_HARVEST)
        assertThat(outcome.reason).isNull()
        assertThat(outcome.hasAudio).isTrue()
    }

    @Test
    fun `the fallback wins when the preferred route produces nothing`() {
        val oem = FakeStrategy(
            CaptureRoute.OEM_FILE_HARVEST,
            produces = null,
            failure = AudioMissingReason.ATTRIBUTION_FAILED,
        )
        val app = FakeStrategy(CaptureRoute.APP_MIC, produces = appFile)

        val outcome = router(oem, app).runCall()

        assertThat(outcome.file).isEqualTo(appFile)
        assertThat(outcome.route).isEqualTo(CaptureRoute.APP_MIC)
    }

    @Test
    fun `an unsupported strategy is never started and is still reported`() {
        // The false branch is the one that runs on most of the fleet
        // (CONVENTIONS-CLIENT.md §10).
        val oem = FakeStrategy(
            CaptureRoute.OEM_FILE_HARVEST,
            supported = false,
            failure = AudioMissingReason.OEM_RECORDER_OFF,
        )
        val app = FakeStrategy(CaptureRoute.APP_MIC, produces = appFile)

        val outcome = router(oem, app).runCall()

        assertThat(oem.started).isFalse()
        assertThat(oem.stopped).isFalse()
        assertThat(outcome.route).isEqualTo(CaptureRoute.APP_MIC)
        // Still in the report: "not available" is a fact an admin acts on.
        val oemAttempt = outcome.attempts.single { it.route == CaptureRoute.OEM_FILE_HARVEST }
        assertThat(oemAttempt.started).isFalse()
        assertThat(oemAttempt.reason).isEqualTo(AudioMissingReason.OEM_RECORDER_OFF)
    }

    @Test
    fun `a recorder that throws on start degrades instead of losing the call`() {
        // UC-14. A device whose microphone is held by the dialer must not take
        // the call down with it.
        val app = FakeStrategy(
            CaptureRoute.APP_MIC,
            throwOnStart = true,
            failure = AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE,
        )

        val outcome = router(app).runCall()

        assertThat(outcome.file).isNull()
        assertThat(outcome.route).isEqualTo(CaptureRoute.NONE)
        assertThat(outcome.reason).isEqualTo(AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE)
    }

    @Test
    fun `total failure reports the PREFERRED route's reason`() {
        // "The handset's own recorder is switched off" is what an admin acts
        // on; "the microphone fallback also returned silence" is a consequence.
        val oem = FakeStrategy(
            CaptureRoute.OEM_FILE_HARVEST,
            supported = false,
            failure = AudioMissingReason.OEM_RECORDER_OFF,
        )
        val app = FakeStrategy(
            CaptureRoute.APP_MIC,
            produces = null,
            failure = AudioMissingReason.CAPTURE_RETURNED_SILENCE,
        )

        val outcome = router(oem, app).runCall()

        assertThat(outcome.reason).isEqualTo(AudioMissingReason.OEM_RECORDER_OFF)
        assertThat(outcome.attempts.map { it.route })
            .containsExactly(CaptureRoute.OEM_FILE_HARVEST, CaptureRoute.APP_MIC)
            .inOrder()
    }

    @Test
    fun `every strategy gets its own destination file`() {
        // Two strategies writing one path is how a fallback silently truncates
        // the preferred route's output, and it looks like a corrupt recording
        // rather than a bug.
        val targets = mutableListOf<File>()
        val oem = FakeStrategy(CaptureRoute.OEM_FILE_HARVEST, produces = oemFile)
        val app = FakeStrategy(CaptureRoute.APP_MIC, produces = appFile)

        CaptureRouter(listOf(oem, app)).apply {
            start { strategy -> File("${strategy.route.wire}.m4a").also(targets::add) }
            stop()
        }

        assertThat(targets.map { it.name }).containsNoDuplicates()
    }

    @Test
    fun `an outcome always carries exactly one of a file or a reason`() {
        // The two fields the panel reads must never disagree: a call with a
        // file AND a reason, or with neither, is a row nobody can interpret.
        val withAudio = router(FakeStrategy(CaptureRoute.APP_MIC, produces = appFile)).runCall()
        assertThat(withAudio.file).isNotNull()
        assertThat(withAudio.reason).isNull()

        val without = router(
            FakeStrategy(CaptureRoute.APP_MIC, produces = null, failure = AudioMissingReason.NO_PERMISSION),
        ).runCall()
        assertThat(without.file).isNull()
        assertThat(without.reason).isNotNull()
    }

    @Test
    fun `an empty router yields a reason rather than a null route`() {
        val outcome = router().runCall()

        assertThat(outcome.route).isEqualTo(CaptureRoute.NONE)
        assertThat(outcome.reason).isEqualTo(AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE)
    }

    @Test
    fun `a second call does not inherit the first call's attempts`() {
        val app = FakeStrategy(CaptureRoute.APP_MIC, produces = appFile)
        val router = router(app)

        router.runCall()
        val second = router.runCall()

        assertThat(second.attempts).hasSize(1)
    }

    @Test
    fun `the stub OEM locator returns nothing, which is the fail-closed answer`() {
        // A placeholder that captured everything by default would be the exact
        // failure the capture package exists to prevent.
        val proof = Decision.Capture(
            subscriptionId = 1,
            registeredNumber = "+998901112233",
            answeredAtEpochMillis = 0L,
            endedAtEpochMillis = 1_000L,
        )

        assertThat(NoOpOemRecordingLocator("test").locate(proof)).isNull()
    }

    @Test
    fun `live recorders are stopped before the post-hoc harvest polls, and preference still picks the winner`() {
        // The microphone must stop at hang-up; the harvest may take seconds
        // to find the handset's file. Stopped in that order, the winner is
        // still the preferred (harvest) route.
        val order = mutableListOf<String>()
        class Ordered(
            private val name: String,
            override val postHoc: Boolean,
            private val nominal: CaptureRoute,
            private val produces: File?,
        ) : RecordingStrategy {
            override val route: CaptureRoute get() = nominal
            override fun isSupported(): Boolean = true
            override fun start(target: File) = Unit
            override fun stop(): File? { order += name; return produces }
            override fun lastFailure(): AudioMissingReason? = null
        }
        val router = router(
            Ordered("oem", postHoc = true, CaptureRoute.OEM_FILE_HARVEST, oemFile),
            Ordered("mic", postHoc = false, CaptureRoute.APP_MIC, appFile),
        )

        val outcome = router.runCall()

        assertThat(order).containsExactly("mic", "oem").inOrder()
        assertThat(outcome.route).isEqualTo(CaptureRoute.OEM_FILE_HARVEST)
        assertThat(outcome.file).isEqualTo(oemFile)
    }
}
