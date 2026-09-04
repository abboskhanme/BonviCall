package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import uz.bonvi.call.R
import uz.bonvi.call.ui.StubScreen

/**
 * E3 — the OEM-specific steps (MIUI, EMUI, ColorOS, One UI). Shown ONLY on the
 * manufacturers that need them, decided by capability, never by a version.
 *
 * Stub. The destination and its route are settled in T22; T63 replaces this
 * body and does not touch the navigation graph.
 */
@Composable
fun EnrolOemStepsScreen() {
    StubScreen(titleRes = R.string.enrol_oem_title, task = "T63")
}
