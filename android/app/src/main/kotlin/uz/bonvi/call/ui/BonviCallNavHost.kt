package uz.bonvi.call.ui

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import uz.bonvi.call.ui.calls.CallsScreen
import uz.bonvi.call.ui.diagnostics.DiagnosticsScreen
import uz.bonvi.call.ui.enrolment.EnrolCodeScreen
import uz.bonvi.call.ui.enrolment.EnrolDoneScreen
import uz.bonvi.call.ui.enrolment.EnrolOemStepsScreen
import uz.bonvi.call.ui.enrolment.EnrolPermissionsScreen
import uz.bonvi.call.ui.enrolment.EnrolSimScreen
import uz.bonvi.call.ui.enrolment.EnrolVerifyScreen
import uz.bonvi.call.ui.home.HomeScreen

/**
 * The navigation graph. Declared up front, in one place, so the Phase 4 tasks
 * fill screen BODIES and never touch the graph — the same reason the panel's
 * route table is settled in T21.
 *
 * The enrolment path is SPEC §8.2's E1 → E6 and its order is the order of the
 * document. Two of the six are conditional and that is a routing decision, not
 * a screen decision:
 *   • [Routes.ENROL_OEM_STEPS] (E3) is shown only on the OEMs that need it
 *     (MIUI, EMUI, ColorOS, One UI battery managers);
 *   • [Routes.ENROL_SIM] (E4) is shown only on dual-SIM handsets.
 * T63 decides both by asking a capability, never by checking a version.
 *
 * `ui/` reaches `data/remote` and `capture/` through `domain/` and NEVER
 * directly — `ArchitectureRulesTest` fails the build otherwise. That is the one
 * layering rule worth enforcing without a module system, because it decides
 * whether the enrolment screens can be tested without a phone.
 */
object Routes {
    const val ENROL_CODE = "enrol/code"
    const val ENROL_PERMISSIONS = "enrol/permissions"
    const val ENROL_OEM_STEPS = "enrol/oem"
    const val ENROL_SIM = "enrol/sim"
    const val ENROL_VERIFY = "enrol/verify"
    const val ENROL_DONE = "enrol/done"

    const val HOME = "home"
    const val CALLS = "calls"
    const val DIAGNOSTICS = "diagnostics"

    /** Every destination, so a test can assert the graph has no orphan. */
    val ALL: List<String> = listOf(
        ENROL_CODE, ENROL_PERMISSIONS, ENROL_OEM_STEPS, ENROL_SIM, ENROL_VERIFY, ENROL_DONE,
        HOME, CALLS, DIAGNOSTICS,
    )
}

@Composable
fun BonviCallNavHost(
    navController: NavHostController = rememberNavController(),
    /**
     * Where the app opens. E1 until an installation is bound and verified, the
     * home screen afterwards. T61 supplies the real answer from the session
     * store; the default keeps the scaffold honest — an unenrolled phone must
     * not land on a home screen that shows nothing.
     */
    startDestination: String = Routes.ENROL_CODE,
) {
    NavHost(navController = navController, startDestination = startDestination) {
        composable(Routes.ENROL_CODE) { EnrolCodeScreen() }
        composable(Routes.ENROL_PERMISSIONS) { EnrolPermissionsScreen() }
        composable(Routes.ENROL_OEM_STEPS) { EnrolOemStepsScreen() }
        composable(Routes.ENROL_SIM) { EnrolSimScreen() }
        composable(Routes.ENROL_VERIFY) { EnrolVerifyScreen() }
        composable(Routes.ENROL_DONE) { EnrolDoneScreen() }

        composable(Routes.HOME) { HomeScreen() }
        composable(Routes.CALLS) { CallsScreen() }
        composable(Routes.DIAGNOSTICS) { DiagnosticsScreen() }
    }
}
