package uz.bonvi.call.ui.enrolment

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import uz.bonvi.call.R
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E3 — the OEM-specific steps** (SPEC §8.2).
 *
 * Shown **only** on the manufacturers that need them: autostart, battery lock,
 * "allow background activity". Each has that OEM's own screen path.
 *
 * ⚠️ Where the platform exposes no check, the step is **user-attested and
 * recorded as `unknown`, never as `granted`**. A false green here is exactly
 * how R3 stays invisible: the phone claims autostart is on, the OEM kills the
 * service overnight, and the first anyone hears of it is a month of missing
 * calls. `CapabilityChecks` returns `UNKNOWN` for `oem_autostart` for the same
 * reason.
 *
 * The photographs T107 shoots slot in here; until then the path is text, which
 * is still better than a screen that pretends the step does not exist.
 */
@Composable
fun EnrolOemStepsScreen(viewModel: EnrolmentViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    val context = LocalContext.current
    val steps = oemSteps(Capabilities.manufacturer)

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_oem_title),
        onStuck = viewModel::onStuck,
    ) {
        steps.forEach { step ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text(text = step.path, style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(R.string.perm_autostart_why))
                    Button(
                        onClick = { context.openSettingsFor(Capability.OEM_AUTOSTART) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.common_open_settings))
                    }
                }
            }
        }
    }
}

/** One OEM step: the manufacturer's own path, as a person reads it on screen. */
data class OemStep(val path: String)

/**
 * The manufacturers SPEC §8.2 names. Anything else gets no E3 at all — showing
 * an irrelevant step costs a minute of a fifteen-minute budget and teaches the
 * agent that the instructions do not match their phone.
 *
 * The paths stay English here because they are the OEM's own menu labels, which
 * are not translated on the handset either; the SENTENCE explaining why is
 * Uzbek and lives in strings.xml (CONVENTIONS.md §14).
 */
fun oemSteps(manufacturer: String): List<OemStep> = when (manufacturer.lowercase()) {
    "xiaomi", "redmi", "poco" -> listOf(
        OemStep("Settings › Apps › BonviCall › Autostart"),
        OemStep("Settings › Battery › App battery saver › BonviCall › No restrictions"),
    )
    "huawei", "honor" -> listOf(
        OemStep("Settings › Battery › App launch › BonviCall › Manage manually"),
    )
    "oppo", "realme", "oneplus" -> listOf(
        OemStep("Settings › Battery › Background usage › BonviCall › Allow"),
        OemStep("Settings › Apps › Auto-start › BonviCall"),
    )
    "samsung" -> listOf(
        OemStep("Settings › Battery › Background usage limits › Never sleeping apps"),
    )
    "vivo" -> listOf(
        OemStep("Settings › Battery › High background power consumption › BonviCall"),
    )
    else -> emptyList()
}
