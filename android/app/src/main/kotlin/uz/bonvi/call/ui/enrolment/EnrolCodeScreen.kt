package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * E1 — the enrolment code. Prefilled from the bonvicall://enrol deep link so an
 * agent never types a code by hand.
 *
 * Stub. The destination and its route are settled in T22; T61 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun EnrolCodeScreen() {
    StubScreen(titleRes = R.string.enrol_code_title, task = "T61")
}
