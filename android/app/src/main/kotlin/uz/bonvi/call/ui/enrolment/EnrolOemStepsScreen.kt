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
import uz.bonvi.call.domain.OemGuidance
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E3 — the OEM-specific steps** (SPEC §8.2).
 *
 * Shown **only** on the manufacturers that need them: autostart, battery lock,
 * "allow background activity". Each has that OEM's own screen path, and
 * [OemGuidance] is where those paths live — the flow asks the same object
 * whether this screen appears at all, so a phone can never be routed to an
 * empty E3.
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
    val steps = OemGuidance.stepsFor(Capabilities.manufacturer)

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_oem_title),
        onStuck = viewModel::onStuck,
    ) {
        Text(stringResource(R.string.enrol_oem_explain))

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

        // The way OUT, and there is only one of it.
        //
        // Nothing on this screen can be verified by the platform, so "I did it"
        // and "I will do it later" are the same claim as far as the app is
        // concerned — offering both would be a choice with no consequence. The
        // step is recorded as `unknown` either way, which keeps a phone that
        // skipped it visible to the panel instead of pretending it is fine.
        Button(
            onClick = viewModel::onOemStepsFinished,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(stringResource(R.string.common_continue))
        }
    }
}
