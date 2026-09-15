package uz.bonvi.call.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import uz.bonvi.call.enrolment.EnrolmentStep
import uz.bonvi.call.enrolment.EnrolmentViewModel
import uz.bonvi.call.ui.calls.MyCallsScreen
import uz.bonvi.call.ui.diagnostics.DiagnosticsScreen
import uz.bonvi.call.ui.enrolment.EnrolCodeScreen
import uz.bonvi.call.ui.enrolment.EnrolDoneScreen
import uz.bonvi.call.ui.enrolment.EnrolOemStepsScreen
import uz.bonvi.call.ui.enrolment.EnrolPermissionsScreen
import uz.bonvi.call.ui.enrolment.EnrolSimScreen
import uz.bonvi.call.ui.enrolment.EnrolVerifyScreen
import uz.bonvi.call.ui.enrolment.collectAsStateWithLifecycleCompat
import uz.bonvi.call.ui.home.HomeScreen
import uz.bonvi.call.ui.permissions.PermissionsScreen

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

    /** E2's rows, reachable for ever rather than only during enrolment: a
     *  permission skipped on day one is otherwise unreachable from inside the
     *  app that needs it. */
    const val PERMISSIONS = "permissions"

    /** Every destination, so a test can assert the graph has no orphan. */
    val ALL: List<String> = listOf(
        ENROL_CODE, ENROL_PERMISSIONS, ENROL_OEM_STEPS, ENROL_SIM, ENROL_VERIFY, ENROL_DONE,
        HOME, CALLS, DIAGNOSTICS, PERMISSIONS,
    )

    /**
     * Where each enrolment step is drawn.
     *
     * The ViewModel owns the STEP and the graph owns the ROUTE, and until
     * [FollowEnrolmentStep] existed nothing joined them: E1 redeemed the code,
     * moved the step to `PERMISSIONS`, and the phone stayed on E1 with the
     * agent's name freshly printed on it. From the outside that is
     * indistinguishable from a dead server — the first real handset pressed
     * "Davom etish" repeatedly and the redeem kept succeeding, because a repeat
     * from the same fingerprint on a pending installation is deliberately
     * idempotent server-side. Exhaustive `when`, so a seventh step cannot be
     * added without deciding where it is shown.
     */
    fun forStep(step: EnrolmentStep): String = when (step) {
        EnrolmentStep.CODE -> ENROL_CODE
        EnrolmentStep.PERMISSIONS -> ENROL_PERMISSIONS
        EnrolmentStep.OEM_STEPS -> ENROL_OEM_STEPS
        EnrolmentStep.SIM -> ENROL_SIM
        EnrolmentStep.VERIFY -> ENROL_VERIFY
        EnrolmentStep.DONE -> ENROL_DONE
    }
}

@Composable
private fun enrolmentViewModel(
    navController: NavHostController,
    entry: androidx.navigation.NavBackStackEntry,
): EnrolmentViewModel {
    val graph = remember(entry) { navController.getBackStackEntry(Routes.ENROL_CODE) }
    return hiltViewModel(graph)
}

/**
 * Moves the graph to whatever step the shared ViewModel is on.
 *
 * Placed on every enrolment destination rather than around the NavHost,
 * because the ViewModel is scoped to E1's back-stack entry and can only be
 * reached from inside a destination.
 *
 * The whole enrolment is ONE forward-only transaction: the code is single-use,
 * so returning to E1 to re-enter it is an unrecoverable loop. Everything above
 * E1 is therefore replaced rather than stacked, and E1 itself stays at the
 * bottom because it hosts the ViewModel the six screens share — popping it
 * would take the transaction with it.
 */
@Composable
private fun FollowEnrolmentStep(
    viewModel: EnrolmentViewModel,
    navController: NavHostController,
    thisRoute: String,
) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    val target = Routes.forStep(state.step)
    LaunchedEffect(target, thisRoute) {
        if (target == thisRoute) return@LaunchedEffect
        navController.navigate(target) {
            popUpTo(Routes.ENROL_CODE) { inclusive = false }
            launchSingleTop = true
        }
    }
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
            val viewModel = enrolmentViewModel(navController, entry)
            FollowEnrolmentStep(viewModel, navController, Routes.ENROL_CODE)
            EnrolCodeScreen(
                viewModel = viewModel,
                prefilledCode = entry.arguments?.getString(ARG_CODE) ?: deepLinkCode,
                onOpenDiagnostics = { navController.navigate(Routes.DIAGNOSTICS) },
            )
        }
        composable(Routes.ENROL_PERMISSIONS) { entry ->
            val viewModel = enrolmentViewModel(navController, entry)
            FollowEnrolmentStep(viewModel, navController, Routes.ENROL_PERMISSIONS)
            EnrolPermissionsScreen(viewModel)
        }
        composable(Routes.ENROL_OEM_STEPS) { entry ->
            val viewModel = enrolmentViewModel(navController, entry)
            FollowEnrolmentStep(viewModel, navController, Routes.ENROL_OEM_STEPS)
            EnrolOemStepsScreen(viewModel)
        }
        composable(Routes.ENROL_SIM) { entry ->
            val viewModel = enrolmentViewModel(navController, entry)
            FollowEnrolmentStep(viewModel, navController, Routes.ENROL_SIM)
            EnrolSimScreen(viewModel)
        }
        composable(Routes.ENROL_VERIFY) { entry ->
            val viewModel = enrolmentViewModel(navController, entry)
            FollowEnrolmentStep(viewModel, navController, Routes.ENROL_VERIFY)
            EnrolVerifyScreen(
                viewModel = viewModel,
                line1Number = simFacts?.line1Number,
                carrierName = simFacts?.carrierName,
                simSlot = simFacts?.slotIndex,
            )
        }
        composable(Routes.ENROL_DONE) { entry ->
            val viewModel = enrolmentViewModel(navController, entry)
            FollowEnrolmentStep(viewModel, navController, Routes.ENROL_DONE)
            EnrolDoneScreen(
                viewModel = viewModel,
                onOpenDiagnostics = { navController.navigate(Routes.DIAGNOSTICS) },
                // The way out of enrolment, and the last screen that may pop
                // E1: the shared ViewModel is not needed past this point, and
                // leaving the six steps on the stack would put a back button
                // into a consumed enrolment.
                onFinish = {
                    navController.navigate(Routes.HOME) {
                        popUpTo(Routes.ENROL_CODE) { inclusive = true }
                        launchSingleTop = true
                    }
                },
            )
        }

        composable(Routes.HOME) {
            HomeScreen(
                onOpenCalls = { navController.navigate(Routes.CALLS) },
                onOpenDiagnostics = { navController.navigate(Routes.DIAGNOSTICS) },
                onOpenPermissions = { navController.navigate(Routes.PERMISSIONS) },
                onReEnrol = { navController.navigate(Routes.ENROL_CODE) },
            )
        }
        composable(Routes.CALLS) { MyCallsScreen() }
        composable(Routes.DIAGNOSTICS) { DiagnosticsScreen() }
        composable(Routes.PERMISSIONS) { PermissionsScreen() }
    }
}
