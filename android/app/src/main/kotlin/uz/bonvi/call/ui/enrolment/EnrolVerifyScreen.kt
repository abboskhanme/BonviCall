package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * E5 — number verification. Route 1 (SIM MSISDN) runs invisibly; route 2 is the
 * callback challenge. Refuses to start when the receiver is down and says so in
 * Uzbek rather than failing silently (SPEC §9).
 *
 * Stub. The destination and its route are settled in T22; T64 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun EnrolVerifyScreen() {
    StubScreen(titleRes = R.string.enrol_verify_title, task = "T64")
}
