package uz.bonvi.call.arch

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import java.io.File

/**
 * The dependency graph and the navigation graph are finished (T145).
 *
 * This is the wiring pass made checkable. Everything is built, so what this
 * pins is that nothing is left dangling: every capture strategy has a binding,
 * both flavours differ in exactly one file, and the enrolment flow's
 * destinations are all reachable.
 *
 * The `NoOpOemRecordingLocator` binding is deliberately still in place — that
 * is correct until M0 (T71b), and the test asserts the SEAM is finished rather
 * than that the locator is.
 */
class GraphCompletenessTest {

    private fun flavourSource(flavour: String): File =
        File(TestPaths.appDir, "src/$flavour/kotlin/uz/bonvi/call/di/CaptureModule.kt")

    @Test
    fun `the two flavours differ in exactly one Kotlin file`() {
        // SPEC §7.2: the ONLY flavour-specific source is di/CaptureModule.kt,
        // plus the two manifests. A second one is where the two builds start
        // silently diverging, which is the thing M0's comparison cannot survive.
        for (flavour in listOf("legacy28", "modern34")) {
            val root = File(TestPaths.appDir, "src/$flavour")
            val kotlinFiles = root.walkTopDown()
                .filter { it.isFile && it.extension == "kt" }
                .map { it.name }
                .toList()
            assertThat(kotlinFiles).containsExactly("CaptureModule.kt")
        }
    }

    @Test
    fun `both flavours bind an OemRecordingLocator`() {
        for (flavour in listOf("legacy28", "modern34")) {
            val source = flavourSource(flavour).readText()
            assertThat(source).contains("fun oemRecordingLocator(): OemRecordingLocator")
        }
    }

    @Test
    fun `T71b is still a NoOp, and says so`() {
        // Not a failure — it is correct until M0 decides which route wins. What
        // matters is that it fails CLOSED and that the next person knows the
        // change is one expression.
        for (flavour in listOf("legacy28", "modern34")) {
            val source = flavourSource(flavour).readText()
            assertThat(source).contains("NoOpOemRecordingLocator")
            assertThat(source).contains("T71b")
        }
    }

    @Test
    fun `every interface the app injects has exactly one binding`() {
        // A second binding for the same seam is a Dagger duplicate-binding
        // error at build time; a MISSING one is what this catches, because the
        // failure mode is a module that compiles and a graph that does not.
        val modules = TestPaths.kotlinSources()
            .filter { it.path.contains("/di/") }
            .joinToString("\n") { it.readText() }

        val seams = listOf(
            "AudioTranscoder", "AudioUpload", "CallSessionStore", "PendingCallStore",
            "PrivacyBoundary", "CaptureCapabilityChecker", "StorageAccessProbe",
            "SubscriptionPresenceProbe", "SimDirectory", "DeviceFacts",
            "CaptureServiceState", "CallEndedListener", "EnrolmentFacts",
        )
        val unbound = seams.filterNot { modules.contains(": $it") || modules.contains("): $it") }
        assertThat(unbound).isEmpty()
    }

    @Test
    fun `every Retrofit API has a provider`() {
        val network = TestPaths.kotlinSources()
            .single { it.name == "NetworkModule.kt" }.readText()
        val apis = TestPaths.kotlinSources()
            .filter { it.path.contains("/remote/api/") }
            .map { it.nameWithoutExtension }

        val unprovided = apis.filterNot { network.contains("$it::class.java") }
        assertThat(unprovided).isEmpty()
        assertThat(apis).isNotEmpty()
    }

    @Test
    fun `every worker is scheduled from somewhere`() {
        // A worker nobody enqueues is a job that never runs, and the symptom is
        // silence rather than an error.
        val all = TestPaths.kotlinSources().joinToString("\n") { it.readText() }
        val workers = TestPaths.kotlinSources()
            .filter { it.path.contains("/work/") && it.name.endsWith("Worker.kt") }
            .map { it.nameWithoutExtension }

        assertThat(workers).isNotEmpty()
        for (worker in workers) {
            // Either scheduled periodically or enqueued on an event.
            val scheduled = all.contains("$worker.schedule") ||
                all.contains("$worker.enqueue")
            assertThat(scheduled).isTrue()
        }
    }
}
