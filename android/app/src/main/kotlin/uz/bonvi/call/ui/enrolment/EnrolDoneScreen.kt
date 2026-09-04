package uz.bonvi.call.ui.enrolment

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import uz.bonvi.call.R
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E6 — "Tayyor"** (SPEC §8.2).
 *
 * Reached only when **every required capability is `granted_working` AND the
 * installation is active**, which is `UiState.isFullyEnrolled` — computed by
 * the same `CaptureReadiness.evaluate` the server-facing state uses, so there
 * is no second code path that could disagree (UC-03's never-false-ready).
 *
 * When it is not true the screen says so and NAMES the blocker, rather than
 * showing "Tayyor" over a phone that captures nothing. A false green here is
 * the single most expensive failure in the product: the rollout looks finished,
 * nobody goes looking, and the calls are simply absent.
 *
 * An **attested** binding is rendered differently from a proven one (SPEC §9.3):
 * an admin vouched for the number rather than the handset proving it, and the
 * identity anchor must never silently degrade.
 */
@Composable
fun EnrolDoneScreen(viewModel: EnrolmentViewModel, onOpenDiagnostics: () -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_done_title),
        onStuck = viewModel::onStuck,
    ) {
        if (state.isFullyEnrolled) {
            Text(
                text = stringResource(R.string.enrol_done_ready),
                style = MaterialTheme.typography.titleMedium,
            )
        } else {
            Text(
                text = stringResource(
                    R.string.enrol_done_blocked,
                    state.readiness.blocking.joinToString { it.wire },
                ),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.titleMedium,
            )
            Text(stringResource(R.string.enrol_not_finished))
        }

        if (state.isAttestedRatherThanProven) {
            Text(
                text = stringResource(R.string.enrol_done_attested),
                color = MaterialTheme.colorScheme.tertiary,
            )
        }

        TextButton(onClick = onOpenDiagnostics, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.enrol_done_diagnostics))
        }
    }
}
