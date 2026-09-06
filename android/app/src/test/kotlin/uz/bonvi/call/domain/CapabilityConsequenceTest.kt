package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * **E2 must always be advanceable** (UC-14).
 *
 * ═══ The bug this exists to stop coming back ═══════════════════════════════
 * E2 advanced only on `result.isWorking || capability in OPTIONAL`, and
 * `OPTIONAL` was `{CONTACTS, OEM_AUTOSTART}`. So a `granted_not_working`
 * microphone — the exact case S1 predicted for a Xiaomi, and the case the
 * app's own text says retrying will not fix — left the agent on that screen
 * with no way forward at all. It stranded a real person on a real handset.
 *
 * A phone whose microphone the OEM blocks is **a working installation that
 * logs calls without audio**: `recording_route_unavailable` exists for it, the
 * gap report counts it, the panel renders it. Refusing to enrol it turns a
 * degraded-but-useful install into no install, which is strictly worse for the
 * same handset — and invisible, because the phone never reaches the funnel.
 *
 * The check itself was right. Only the consequence of failing it was wrong.
 */
class CapabilityConsequenceTest {

    @Test
    fun `every capability can be continued past`() {
        // The assertion that matters. There is no capability whose failure is
        // the end of the flow, because there is no capability whose failure
        // makes an installation worth less than no installation.
        for (capability in Capability.entries) {
            assertThat(CapabilityConsequence.of(capability)).isNotNull()
        }
    }

    @Test
    fun `no code path can strand an agent on a permission step`() {
        // Grepping the ViewModel, because the failure was a single boolean and
        // it is exactly the kind of thing that gets re-tightened by somebody
        // fixing a different bug.
        val viewModel = TestPaths.kotlinSources()
            .single { it.name == "EnrolmentViewModel.kt" }.readText()
        assertThat(viewModel).contains("fun onContinueWithout(capability: Capability)")
        // The old, stranding condition must not return.
        assertThat(viewModel).doesNotContain("capability in CaptureReadiness.OPTIONAL")
    }

    @Test
    fun `the screen offers the control on every failing step, not just optional ones`() {
        val screen = TestPaths.kotlinSources()
            .single { it.name == "EnrolPermissionsScreen.kt" }.readText()
        assertThat(screen).contains("if (!alreadyWorking)")
        assertThat(screen).contains("viewModel.onContinueWithout(capability)")
    }

    @Test
    fun `a microphone failure costs audio, not the installation`() {
        // The Xiaomi case: calls are still qayd etiladi, just not yozib
        // olinadi. That distinction is the product, and this is where a person
        // meets it.
        assertThat(CapabilityConsequence.of(Capability.MICROPHONE))
            .isEqualTo(CapabilityConsequence.AUDIO_ONLY)
        assertThat(CapabilityConsequence.of(Capability.STORAGE_ACCESS))
            .isEqualTo(CapabilityConsequence.AUDIO_ONLY)
    }

    @Test
    fun `capture-blocking capabilities say so plainly rather than blocking the flow`() {
        for (capability in listOf(
            Capability.PHONE_STATE,
            Capability.CALL_LOG,
            Capability.NOTIFICATIONS,
            Capability.BATTERY_EXEMPTION,
        )) {
            assertThat(CapabilityConsequence.of(capability))
                .isEqualTo(CapabilityConsequence.CAPTURE_BLOCKED)
        }
    }

    @Test
    fun `contacts and click-to-call cost nothing that matters to capture`() {
        assertThat(CapabilityConsequence.of(Capability.CONTACTS))
            .isEqualTo(CapabilityConsequence.NONE)
        // UC-16 stops working; capture does not.
        assertThat(CapabilityConsequence.of(Capability.CALL_PHONE))
            .isEqualTo(CapabilityConsequence.NONE)
    }

    @Test
    fun `continuing keeps the CHECKED result rather than overwriting it`() {
        // `denied` and `granted_not_working` are different problems and the
        // funnel needs to know which — overwriting with "skipped" would tell
        // the panel the agent chose to skip a permission the OEM was blocking.
        val viewModel = TestPaths.kotlinSources()
            .single { it.name == "EnrolmentViewModel.kt" }.readText()
        assertThat(viewModel).contains("if (existing == null)")
    }

    @Test
    fun `a blocked install is still a real install the panel can see`() {
        // CaptureReadiness already models BLOCKED distinctly from CAPTURING.
        // An enrolled handset reporting BLOCKED is visible to an admin; an
        // unenrolled one is not, which is the whole argument for letting them
        // through.
        val states = CaptureReadiness.evaluate(
            states = mapOf(Capability.MICROPHONE to CapabilityState.GRANTED_NOT_WORKING),
            installationActive = true,
            numberVerified = true,
        )
        assertThat(states.state).isEqualTo(CaptureReadiness.CaptureState.BLOCKED)
        assertThat(states.blocking).contains(Capability.MICROPHONE)
    }

    @Test
    fun `E6 never shows a wire identifier to a salesperson`() {
        // `phone_state` on somebody's screen is an English leak (§14) and tells
        // them nothing.
        val done = TestPaths.kotlinSources()
            .single { it.name == "EnrolDoneScreen.kt" }.readText()
        assertThat(done).doesNotContain("it.wire")
        assertThat(done).contains("stringResource(it.titleRes())")
    }
}
