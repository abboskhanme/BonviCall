package uz.bonvi.call.ui

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.TestPaths
import uz.bonvi.call.enrolment.EnrolmentStep

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
    fun `every enrolment step has a registered destination`() {
        // The ViewModel owns the step and the graph owns the route. Nothing
        // joined them once: E1 redeemed the code, moved the step to E2, and the
        // phone stayed on E1 with the agent's name on it — from the outside
        // identical to a dead server, and a live handset sat there pressing
        // "Davom etish" while every redeem succeeded.
        for (step in EnrolmentStep.entries) {
            assertThat(Routes.ALL).contains(Routes.forStep(step))
        }
    }

    @Test
    fun `each enrolment step has its own screen`() {
        // Two steps sharing a route means one of them can never be reached, and
        // the symptom is a flow that stops rather than an error.
        val routes = EnrolmentStep.entries.map { Routes.forStep(it) }
        assertThat(routes).containsNoDuplicates()
    }

    @Test
    fun `every enrolment destination follows the step`() {
        // The mapping above is worthless if a destination does not observe it.
        // Six screens, six effects — a seventh screen added without one is the
        // same dead end this test exists to have caught.
        val followed = FOLLOW_CALL.findAll(navHostSource).map { it.groupValues[1] }.toList()
        assertThat(followed).containsExactly(
            "ENROL_CODE",
            "ENROL_PERMISSIONS",
            "ENROL_OEM_STEPS",
            "ENROL_SIM",
            "ENROL_VERIFY",
            "ENROL_DONE",
        )
    }

    @Test
    fun `the enrolment flow never pops the screen that hosts its ViewModel`() {
        // E1 is the back-stack entry the six screens share a ViewModel through.
        // Popping it inclusively would take the whole enrolment transaction with
        // it, and `getBackStackEntry` would throw rather than navigate — a crash
        // mid-install instead of a stall.
        assertThat(navHostSource).contains("popUpTo(Routes.ENROL_CODE) { inclusive = false }")
    }

    @Test
    fun `an enrolled phone opens on the home screen, not on E1`() {
        // T61. Every launch used to land on E1, which then walked forward
        // through the whole flow — including E5, which would have started a
        // fresh callback challenge on a phone verified weeks ago. The refresh
        // token is the proof of a finished enrolment: the server issues the
        // real pair only after the number is proven.
        val activity = TestPaths.kotlinSources()
            .single { it.name == "MainActivity.kt" }
            .readText()
        assertThat(activity).contains("startDestination = startDestination()")
        assertThat(activity).contains("session.snapshot.refreshToken != null")
        assertThat(activity).contains("Routes.HOME")
    }

    @Test
    fun `enrolment has a way out, and the home screen has somewhere to go`() {
        // Three finished screens with no route into them is the same bug as a
        // step that never navigates: MyCallsScreen and the diagnostics screen
        // were both complete and unreachable from the app's own home.
        assertThat(navHostSource).contains("onFinish =")
        assertThat(navHostSource).contains("onOpenCalls = { navController.navigate(Routes.CALLS) }")
        assertThat(navHostSource).contains(
            "onOpenDiagnostics = { navController.navigate(Routes.DIAGNOSTICS) }",
        )
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

    private companion object {
        /** `FollowEnrolmentStep(viewModel, navController, Routes.X)` → `X`. */
        val FOLLOW_CALL = Regex("""FollowEnrolmentStep\(viewModel, navController, Routes\.(\w+)\)""")
    }
}
