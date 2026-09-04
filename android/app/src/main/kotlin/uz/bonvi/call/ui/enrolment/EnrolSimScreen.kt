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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import uz.bonvi.call.R
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E4 — which SIM is the work number** (SPEC §8.2).
 *
 * Shown only on dual-SIM handsets; a single-SIM phone skips it silently. The
 * choice sets `sim_subscription_id`, and **Guard 1 enforces it on every call
 * from then on** — which makes this the screen the whole privacy boundary rests
 * on. The wrong choice here means the app watches the employee's own SIM, so
 * the row shows the slot, the carrier and the MSISDN where the OS knows it, and
 * the app never picks for them.
 *
 * The MSISDN is a hint for the human and nothing more: it is empty on many
 * Uzbek SIMs, and treating "I don't know" as "yes" is exactly what SPEC §9.1
 * forbids.
 */
@Composable
fun EnrolSimScreen(viewModel: EnrolmentViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_sim_title),
        onStuck = viewModel::onStuck,
    ) {
        Text(stringResource(R.string.enrol_sim_explain))

        state.simOptions.forEach { option ->
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text(
                        text = stringResource(R.string.enrol_sim_slot, option.slotIndex + 1),
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(option.carrierName)
                    // Shown only when the OS actually knows it. An empty line
                    // here is honest; a guessed number would not be.
                    option.msisdn?.let { Text(it) }
                    Button(
                        onClick = { viewModel.onSimChosen(option.subscriptionId) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.common_continue))
                    }
                }
            }
        }
    }
}
