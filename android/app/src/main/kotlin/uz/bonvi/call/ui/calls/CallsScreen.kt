package uz.bonvi.call.ui.calls

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * The employee's own calls (N41, UC-21). Own rows only; the server decides that,
 * not this screen.
 *
 * Stub. The destination and its route are settled in T22; T65 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun CallsScreen() {
    StubScreen(titleRes = R.string.calls_title, task = "T65")
}
