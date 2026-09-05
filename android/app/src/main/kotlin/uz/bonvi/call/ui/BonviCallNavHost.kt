package uz.bonvi.call.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import uz.bonvi.call.enrolment.EnrolmentViewModel
import uz.bonvi.call.ui.calls.MyCallsScreen
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
/** The SIM facts E5 needs, passed in rather than read here: `ui/` must not
 *  touch telephony, and `getLine1Number()` is empty on many Uzbek SIMs anyway
 *  — it is a hint, never evidence (SPEC §9.1). */
data class SimFacts(
    val line1Number: String?,
    val carrierName: String?,
    val slotIndex: Int?,
)

private const val ARG_CODE = "code"

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
private fun enrolmentViewModel(
    navController: NavHostController,
    entry: androidx.navigation.NavBackStackEntry,
): EnrolmentViewModel {
    val graph = remember(entry) { navController.getBackStackEntry(Routes.ENROL_CODE) }
    return hiltViewModel(graph)
}

@Composable
fun BonviCallNavHost(
    navController: NavHostController = rememberNavController(),
    /** From the `bonvicall://enrol?code=…` deep link, so the code is not typed. */
    deepLinkCode: String? = null,
    /** What the OS says about the chosen SIM, read once by the Activity — `ui/`
     *  does not reach into telephony itself. */
    simFacts: SimFacts? = null,
    /**
     * Where the app opens. E1 until an installation is bound and verified, the
     * home screen afterwards. T61 supplies the real answer from the session
     * store; the default keeps the scaffold honest — an unenrolled phone must
     * not land on a home screen that shows nothing.
     */
    startDestination: String = Routes.ENROL_CODE,
) {
    NavHost(navController = navController, startDestination = startDestination) {
        // E1–E6 share ONE ViewModel, scoped to the enrolment graph rather than
        // to a destination. The six screens are one transaction: E2's results
        // decide whether E6 may be reached, E4's SIM choice is what E5
        // verifies, and the number from E1 is on every screen after it (N41).
        // Six ViewModels would mean passing that state between destinations,
        // which is how a half-finished enrolment ends up looking finished.
        composable(Routes.ENROL_CODE) { entry ->
            EnrolCodeScreen(
                viewModel = enrolmentViewModel(navController, entry),
                prefilledCode = entry.arguments?.getString(ARG_CODE) ?: deepLinkCode,
            )
        }
        composable(Routes.ENROL_PERMISSIONS) { entry ->
            EnrolPermissionsScreen(enrolmentViewModel(navController, entry))
        }
        composable(Routes.ENROL_OEM_STEPS) { entry ->
            EnrolOemStepsScreen(enrolmentViewModel(navController, entry))
        }
        composable(Routes.ENROL_SIM) { entry ->
            EnrolSimScreen(enrolmentViewModel(navController, entry))
        }
        composable(Routes.ENROL_VERIFY) { entry ->
            EnrolVerifyScreen(
                viewModel = enrolmentViewModel(navController, entry),
                line1Number = simFacts?.line1Number,
                carrierName = simFacts?.carrierName,
                simSlot = simFacts?.slotIndex,
            )
        }
        composable(Routes.ENROL_DONE) { entry ->
            EnrolDoneScreen(
                viewModel = enrolmentViewModel(navController, entry),
                onOpenDiagnostics = { navController.navigate(Routes.DIAGNOSTICS) },
            )
        }

        composable(Routes.HOME) { HomeScreen() }
        composable(Routes.CALLS) { MyCallsScreen() }
        composable(Routes.DIAGNOSTICS) { DiagnosticsScreen() }
    }
}
