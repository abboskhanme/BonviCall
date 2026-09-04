package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * E2 — one permission at a time, each with one Uzbek sentence of purpose, and
 * a REAL capability check after every grant. A step goes green when the
 * capability works, not when the dialog was dismissed (UC-03).
 *
 * Stub. The destination and its route are settled in T22; T62 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun EnrolPermissionsScreen() {
    StubScreen(titleRes = R.string.enrol_permissions_title, task = "T62")
}
