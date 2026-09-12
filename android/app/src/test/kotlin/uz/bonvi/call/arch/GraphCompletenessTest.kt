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
    fun `the two flavours differ in exactly the capture module and its locator`() {
        // SPEC §7.2's rule was "one file", and T71b is the change that rule was
        // written in anticipation of: each flavour now also carries the locator
        // the module binds, because reaching the same folder through raw paths
        // and through MediaStore is genuinely different code. TWO files, named,
        // and a third is still where the builds start silently diverging —
        // which is the thing M0's comparison cannot survive.
        val expected = mapOf(
            "legacy28" to setOf("CaptureModule.kt", "RawPathOemRecordingLocator.kt"),
            "modern34" to setOf("CaptureModule.kt", "MediaStoreOemRecordingLocator.kt"),
        )
        for ((flavour, files) in expected) {
            val root = File(TestPaths.appDir, "src/$flavour")
            val kotlinFiles = root.walkTopDown()
                .filter { it.isFile && it.extension == "kt" }
                .map { it.name }
                .toSet()
            assertThat(kotlinFiles).isEqualTo(files)
        }
    }

    @Test
    fun `both flavours bind an OemRecordingLocator`() {
        for (flavour in listOf("legacy28", "modern34")) {
            val source = flavourSource(flavour).readText()
            assertThat(source).contains("OemRecordingLocator")
            assertThat(source).contains("@Provides")
        }
    }

    @Test
    fun `T71b is built, and neither flavour is a NoOp any more`() {
        // The inverse of the test that stood here. It asserted the placeholder
        // was still in place, which was correct until a real handset could say
        // where these files land; a Redmi Note 14 on HyperOS answered that on
        // 2026-09-11 and the locators were written against it.
        //
        // Kept rather than deleted, and inverted: a reversed decision keeps its
        // test. If either flavour ever falls back to the NoOp, the fleet goes
        // half-deaf silently — every call would ship `attribution_failed` and
        // look exactly like a handset whose recorder is switched off.
        val bindings = listOf("legacy28", "modern34").associateWith {
            flavourSource(it).readText()
        }
        assertThat(bindings.getValue("legacy28")).contains("RawPathOemRecordingLocator()")
        assertThat(bindings.getValue("modern34")).contains("MediaStoreOemRecordingLocator(")
        for ((_, source) in bindings) {
            // The BINDING, not the word: both files still name the placeholder
            // in their history note, and that note is worth keeping.
            assertThat(source).doesNotContain("= NoOpOemRecordingLocator(")
        }
    }

    @Test
    fun `every interface the app injects has exactly one binding`() {
        // A second binding for the same seam is a Dagger duplicate-binding
        // error at build time; a MISSING one is what this catches, because the
        // failure mode is a module that compiles and a graph that does not.
        val modules = TestPaths.kotlinSources()
            // `invariantSeparatorsPath` throughout this file: a `/`-written path
            // fragment matches nothing against Windows' `\`, so these filters
            // returned EMPTY — and an empty scan makes a completeness test pass
            // vacuously wherever it is not guarded by an `isNotEmpty()`.
            .filter { it.invariantSeparatorsPath.contains("/di/") }
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
            .filter { it.invariantSeparatorsPath.contains("/remote/api/") }
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
            .filter { it.invariantSeparatorsPath.contains("/work/") && it.name.endsWith("Worker.kt") }
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
