package uz.bonvi.call.ui.diagnostics

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * Queue depth, last contact, capability states, capture route. This is what an
 * admin asks the employee to read out during an assisted install (UC-07).
 *
 * Stub. The destination and its route are settled in T22; T66 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun DiagnosticsScreen() {
    StubScreen(titleRes = R.string.diagnostics_title, task = "T66")
}
