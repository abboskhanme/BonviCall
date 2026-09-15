package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertWithMessage
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * **A finished component with no caller passes every test it has.**
 *
 * That sentence is in `docs/STATUS.md` because this build met it four times:
 * a WebSocket router nothing included, a heartbeat endpoint nothing called, a
 * version field read from a header nothing sent, and an enrolment step the
 * navigation never moved to. Each component's own tests were green throughout,
 * because each test supplied the caller the product did not.
 *
 * This is that question asked mechanically: **who calls this in production?**
 * Every row below is a capability the fleet depends on, paired with the call
 * that makes it happen. A row that fails is not a style problem — it is a
 * feature that exists, compiles, is tested, and does nothing on a phone.
 */
class ProductionCallersTest {

    /** file that DECLARES it · the call that uses it · what breaks without it. */
    private val required = listOf(
        Triple(
            "Heartbeat.kt", "heartbeat.send()",
            "the panel shows every handset as a device that has never reported",
        ),
        Triple(
            "CommandRunner.kt", "commands.drain()",
            "a phone that was asleep never collects the commands waiting for it",
        ),
        Triple(
            "CommandRunner.kt", "commands.execute(",
            "a command arrives and nothing carries it out",
        ),
        Triple(
            "RealtimeChannel.kt", "realtime.connect(",
            "click-to-call falls back to a 15-minute poll, by which time every dial is stale",
        ),
        Triple(
            "DialCommand.kt", "dial.execute(",
            "UC-16 acknowledges commands it never dials",
        ),
        Triple(
            "AppUpdater.kt", "updater.update(",
            "a fleet below the minimum version can never update itself (N34)",
        ),
        Triple(
            "Revocation.kt", "revocation.enforceIfRevoked()",
            "a revoked phone keeps the employee's recordings — UC-08's worst state",
        ),
        Triple(
            "CapabilityChecks.kt", "onEnrolmentComplete()",
            "a freshly enrolled phone captures nothing until a reboot or the first call",
        ),
        Triple(
            "CaptureRouterFactory.kt", "factory.forCall(",
            "no call is ever recorded: every row ships with capture_route = none",
        ),
        Triple(
            "CaptureCoordinator.kt", "capture.start(",
            "the recorder is never started when a call is answered",
        ),
        Triple(
            "AudioPipeline.kt", "pipeline.process(",
            "a recording is made and never transcoded, uploaded or deleted",
        ),
        Triple(
            "AudioDrain.kt", "audio.drainOnce()",
            "recordings queue on the phone and nothing ever sends them",
        ),
        Triple(
            "AudioJobRepository.kt", "audioJobs.enqueue(",
            "a captured call never becomes an upload — the file sits on disk for ever",
        ),
        Triple(
            "HeartbeatWorker.kt", "HeartbeatWorker.schedulePeriodic(",
            "the phone reports once and then goes quiet",
        ),
        Triple(
            "CallUploadWorker.kt", "CallUploadWorker.schedulePeriodic(",
            "a queue that failed to drain waits for the next call instead of a retry",
        ),
        Triple(
            "WatchdogWorker.kt", "WatchdogWorker.schedule(",
            "an OEM battery manager stops the service and nothing restarts it (UC-05)",
        ),
        Triple(
            "CaptureCoordinator.kt", "capture.releaseAll()",
            "a capture the call's end never stopped goes on holding the MICROPHONE — " +
                "on a targetSdk 28 build the platform grants that hold, so every " +
                "other app on the employee's own phone records silence until they " +
                "reboot (reported by the fleet on 2026-09-15: Telegram could not " +
                "place a call and its voice messages came out empty)",
        ),
        Triple(
            "CapabilityRefresh.kt", "capabilities.ifChanged(",
            "a permission granted after enrolment is never noticed: the panel goes " +
                "on showing the phone as blocked while it is working",
        ),
        Triple(
            "ContactNameResolver.kt", "contactNames.resolve(",
            "every call ships with contact_name = null: the panel shows a raw " +
                "number instead of the name the employee gave the customer, which " +
                "is the Moi Zvonki defect this product was built to fix",
        ),
    )

    @Test
    fun `every capability the fleet depends on has a caller in production code`() {
        val sources = TestPaths.kotlinSources()
        for ((declaredIn, call, consequence) in required) {
            val callers = sources
                .filterNot { it.name == declaredIn }
                .filter { it.readText().contains(call) }
                .map { it.name }

            assertWithMessage(
                "Nothing calls `$call` outside $declaredIn — so $consequence.",
            ).that(callers).isNotEmpty()
        }
    }

    @Test
    fun `the components these rows name still exist`() {
        // A row whose file was renamed would otherwise pass by looking for a
        // call to something that is gone — the test would keep guarding a
        // component nobody has.
        val names = TestPaths.kotlinSources().map { it.name }.toSet()
        for ((declaredIn, _, _) in required) {
            assertWithMessage("$declaredIn is named by this test and does not exist")
                .that(names).contains(declaredIn)
        }
    }
}
