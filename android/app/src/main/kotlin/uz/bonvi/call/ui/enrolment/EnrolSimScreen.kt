package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * E4 — which SIM is the work number. Shown only on dual-SIM handsets. This is
 * the screen the whole privacy boundary rests on: the wrong choice here means
 * the app watches the employee's own SIM.
 *
 * Stub. The destination and its route are settled in T22; T63 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun EnrolSimScreen() {
    StubScreen(titleRes = R.string.enrol_sim_title, task = "T63")
}
