package uz.bonvi.call.capture

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * The preferred route's seam.
 *
 * The real locators are T71b and are blocked on S1 + M0. What is testable — and
 * load-bearing — today is that **the strategy cannot be pointed at a call it
 * has no proof for**, and that a window matching nothing is the boundary
 * refusing rather than a bug (CONVENTIONS.md §8, SPEC §7.4).
 */
class OemHarvestStrategyTest {

    private val proof = Decision.Capture(
        subscriptionId = 2,
        registeredNumber = "+998901112233",
        answeredAtEpochMillis = 10_000L,
        endedAtEpochMillis = 70_000L,
    )

    private val harvested = File("oem.m4a")

    private fun strategy(
        located: File?,
        recorderReachable: Boolean = true,
    ) = OemHarvestStrategy(
        capture = proof,
        locator = { _ -> located },
        recorderReachable = { recorderReachable },
        // No real waiting in a unit test.
        sleeper = {},
    )

    @Test
    fun `a located file is returned on the OEM route`() {
        val strategy = strategy(located = harvested)

        strategy.start(File("ignored"))

        assertThat(strategy.stop()).isEqualTo(harvested)
        assertThat(strategy.route).isEqualTo(CaptureRoute.OEM_FILE_HARVEST)
        assertThat(strategy.lastFailure()).isNull()
    }

    @Test
    fun `a window that matches nothing is attribution_failed, not a crash`() {
        // The boundary REFUSING. An unmatched recording in that folder is the
        // employee's private call: it is discarded on the device rather than
        // uploaded and sorted out server-side.
        val strategy = strategy(located = null)

        strategy.start(File("ignored"))

        assertThat(strategy.stop()).isNull()
        assertThat(strategy.lastFailure()).isEqualTo(AudioMissingReason.ATTRIBUTION_FAILED)
    }

    @Test
    fun `an unreachable OEM recorder is reported as oem_recorder_off`() {
        // Distinct from attribution_failed on purpose: "the recorder is
        // switched off" and "the boundary refused the file" are two different
        // conversations with an employee.
        val strategy = strategy(located = harvested, recorderReachable = false)

        assertThat(strategy.isSupported()).isFalse()
        assertThat(strategy.lastFailure()).isEqualTo(AudioMissingReason.OEM_RECORDER_OFF)
    }

    @Test
    fun `the locator is given the capture proof and nothing weaker`() {
        // The privacy boundary in its enforced form: locate() takes a
        // Decision.Capture, so a caller that has not passed
        // PrivacyBoundary.evaluate() cannot express the call to it at all.
        var received: Decision.Capture? = null
        val strategy = OemHarvestStrategy(
            capture = proof,
            locator = { capture -> received = capture; null },
            recorderReachable = { true },
        )

        strategy.start(File("ignored"))
        strategy.stop()

        assertThat(received).isEqualTo(proof)
        assertThat(received?.subscriptionId).isEqualTo(2)
    }

    @Test
    fun `the harvest window constants are the measured ones`() {
        // CallSentry's values (S1-RECORDING.md). Widening either widens the
        // privacy boundary, so it must be a one-line diff a reviewer sees.
        assertThat(OemRecordingLocator.PRE_BUFFER_MS).isEqualTo(5_000L)
        assertThat(OemRecordingLocator.POST_BUFFER_MS).isEqualTo(120_000L)
        assertThat(OemRecordingLocator.MIN_FILE_BYTES).isEqualTo(2_048L)
        assertThat(OemRecordingLocator.RETRY_COUNT).isEqualTo(10)
    }

    @Test
    fun `it polls for a file the OEM recorder flushes late, then returns it`() {
        // The whole reason the first real handset shipped app_voice_communication
        // instead of oem_harvest: MIUI wrote the file ~6-7s AFTER the call
        // ended, and a single scan looked once, too early. The strategy must
        // wait for it.
        var attempts = 0
        var slept = 0
        val strategy = OemHarvestStrategy(
            capture = proof,
            locator = { _ -> if (++attempts >= 5) harvested else null },
            recorderReachable = { true },
            sleeper = { slept++ },
        )

        strategy.start(File("ignored"))

        assertThat(strategy.stop()).isEqualTo(harvested)
        // Seen on the fifth scan, taken on the sixth once its size held still.
        assertThat(attempts).isEqualTo(6)
        assertThat(slept).isEqualTo(5) // one wait between each of the first six scans
        assertThat(strategy.lastFailure()).isNull()
    }

    @Test
    fun `a file still being written is not taken until its size settles`() {
        // The OEM writer grows the file through the call and closes it at
        // hang-up. The scan that first sees the file may see it mid-write, and
        // a truncated both-voices recording reads like a short call.
        val growing = File.createTempFile("oem", ".mp3").apply { deleteOnExit() }
        var attempts = 0
        val strategy = OemHarvestStrategy(
            capture = proof,
            locator = { _ ->
                attempts++
                // Grows on the first three scans, then holds still.
                if (attempts <= 3) growing.appendText("x".repeat(1_000))
                growing
            },
            recorderReachable = { true },
            sleeper = {},
        )

        strategy.start(File("ignored"))

        assertThat(strategy.stop()).isEqualTo(growing)
        // Scan 3 wrote the last bytes; scan 4 saw the same size and took it.
        assertThat(attempts).isEqualTo(4)
        assertThat(growing.length()).isEqualTo(3_000L)
    }

    @Test
    fun `a live call's provisional end is bounded to the stop time before it reaches the locator`() {
        // The detector evaluates a ringing call with `endedAt = Long.MAX_VALUE`
        // and that decision is what the router is built from. Unbounded, the
        // window overflowed and matched nothing -- the reason the OEM route
        // never won on the first real handset.
        val live = proof.copy(endedAtEpochMillis = Long.MAX_VALUE)
        var received: Decision.Capture? = null
        val strategy = OemHarvestStrategy(
            capture = live,
            locator = { capture -> received = capture; harvested },
            recorderReachable = { true },
            sleeper = {},
            clock = { 50_000L },
        )

        strategy.start(File("ignored"))
        strategy.stop()

        assertThat(received?.endedAtEpochMillis).isEqualTo(50_000L)
        assertThat(received?.answeredAtEpochMillis).isEqualTo(proof.answeredAtEpochMillis)
    }

    @Test
    fun `a real end time is never widened by the stop clock`() {
        var received: Decision.Capture? = null
        val strategy = OemHarvestStrategy(
            capture = proof, // ends at 70 000
            locator = { capture -> received = capture; harvested },
            recorderReachable = { true },
            sleeper = {},
            clock = { 99_000L },
        )

        strategy.start(File("ignored"))
        strategy.stop()

        assertThat(received?.endedAtEpochMillis).isEqualTo(70_000L)
    }

    @Test
    fun `it gives up after RETRY_COUNT scans and does not wait after the last`() {
        var attempts = 0
        var slept = 0
        val strategy = OemHarvestStrategy(
            capture = proof,
            locator = { _ -> attempts++; null },
            recorderReachable = { true },
            sleeper = { slept++ },
        )

        strategy.start(File("ignored"))

        assertThat(strategy.stop()).isNull()
        assertThat(attempts).isEqualTo(OemRecordingLocator.RETRY_COUNT)
        // A sleep between scans, never after the final one.
        assertThat(slept).isEqualTo(OemRecordingLocator.RETRY_COUNT - 1)
        assertThat(strategy.lastFailure()).isEqualTo(AudioMissingReason.ATTRIBUTION_FAILED)
    }
}
