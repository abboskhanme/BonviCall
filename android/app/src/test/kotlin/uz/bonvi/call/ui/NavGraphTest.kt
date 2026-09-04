package uz.bonvi.call.ui

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths

/**
 * The navigation graph has no orphan destination.
 *
 * T22 declares every destination up front so the Phase 4 tasks fill screen
 * bodies in parallel without editing the graph — the same reason the panel's
 * route table is settled once. T145 finalises it; until then this test is what
 * stops a screen being written and never reachable, or a route being named and
 * never registered.
 */
class NavGraphTest {

    private val navHostSource: String by lazy {
        TestPaths.kotlinSources()
            .single { it.name == "BonviCallNavHost.kt" }
            .readText()
    }

    @Test
    fun `every declared route is registered as a composable destination`() {
        val unregistered = Routes.ALL.filterNot { route ->
            navHostSource.contains("composable(Routes.${constantNameOf(route)})")
        }
        assertThat(unregistered).isEmpty()
    }

    @Test
    fun `the enrolment flow declares all six steps of SPEC section 8_2`() {
        assertThat(Routes.ALL).containsAtLeast(
            Routes.ENROL_CODE,          // E1
            Routes.ENROL_PERMISSIONS,   // E2
            Routes.ENROL_OEM_STEPS,     // E3, conditional on the manufacturer
            Routes.ENROL_SIM,           // E4, conditional on dual SIM
            Routes.ENROL_VERIFY,        // E5
            Routes.ENROL_DONE,          // E6
        )
    }

    @Test
    fun `an unenrolled phone does not open on a home screen`() {
        // The default start destination is E1. A home screen for somebody with
        // no bound installation shows nothing and explains nothing.
        assertThat(navHostSource).contains("startDestination: String = Routes.ENROL_CODE")
    }

    @Test
    fun `route values are unique`() {
        assertThat(Routes.ALL).containsNoDuplicates()
    }

    private fun constantNameOf(route: String): String = when (route) {
        Routes.ENROL_CODE -> "ENROL_CODE"
        Routes.ENROL_PERMISSIONS -> "ENROL_PERMISSIONS"
        Routes.ENROL_OEM_STEPS -> "ENROL_OEM_STEPS"
        Routes.ENROL_SIM -> "ENROL_SIM"
        Routes.ENROL_VERIFY -> "ENROL_VERIFY"
        Routes.ENROL_DONE -> "ENROL_DONE"
        Routes.HOME -> "HOME"
        Routes.CALLS -> "CALLS"
        Routes.DIAGNOSTICS -> "DIAGNOSTICS"
        else -> error("Route $route is in Routes.ALL but has no constant mapping in this test")
    }
}
