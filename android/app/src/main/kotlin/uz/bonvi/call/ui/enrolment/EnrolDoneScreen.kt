package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * E6 — reached ONLY when every required capability is granted_working AND the
 * installation is verified. A "finished" screen that is not true is worse than
 * no screen at all.
 *
 * Stub. The destination and its route are settled in T22; T64 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun EnrolDoneScreen() {
    StubScreen(titleRes = R.string.enrol_done_title, task = "T64")
}
