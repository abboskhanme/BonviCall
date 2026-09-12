package uz.bonvi.call.ui.enrolment

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import uz.bonvi.call.R
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.domain.NumberVerification
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
fun EnrolDoneScreen(
    viewModel: EnrolmentViewModel,
    onOpenDiagnostics: () -> Unit,
    /**
     * Leave enrolment for the home screen.
     *
     * Offered whatever the state, including BLOCKED: a phone that cannot
     * capture yet is still enrolled, the panel can see it, and stranding the
     * agent on the last step of a flow they cannot finish teaches them the app
     * is broken. The home screen repeats the same reason and keeps the number
     * on screen (N41).
     */
    onFinish: () -> Unit = {},
) {
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
            // A phone that captures but cannot record is CAPTURING, not
            // blocked — and saying so stops somebody chasing a fault that is
            // not there (UC-14).
            if (!state.audioAvailable) {
                Text(stringResource(R.string.enrol_done_audio_only))
            }
        } else if (state.readiness.state == CaptureReadiness.CaptureState.NOT_VERIFIED ||
            state.readiness.state == CaptureReadiness.CaptureState.NOT_ENROLLED
        ) {
            // A DIFFERENT problem from a missing capability, and it needs its
            // own sentence: the number is not proven, so the server accepts
            // nothing at all — the provisional token gets the phone through
            // verification and no further. Telling somebody to check their
            // permissions here would send them to the wrong screen.
            Text(
                text = stringResource(R.string.enrol_not_finished),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.titleMedium,
            )
        } else {
            // The install is REAL: the panel can see this handset and knows
            // exactly what is missing. That is the funnel doing its job, and it
            // is why E2 let them get here.
            Text(
                text = stringResource(R.string.enrol_done_blocked),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.titleMedium,
            )
            // Uzbek names, never the wire identifiers — `phone_state` on a
            // salesperson's screen is an English leak (§14) and tells them
            // nothing. Resolved outside the joinToString because
            // stringResource is @Composable and cannot be called in a lambda.
            val missing = state.readiness.blocking.map { stringResource(it.titleRes()) }
            Text(stringResource(R.string.enrol_done_blocked_what, missing.joinToString()))
            Text(stringResource(R.string.enrol_done_blocked_next))
        }

        // SPEC §9.3: an unproven binding is named, and named for what it
        // actually is. Two of the four routes vouch rather than prove, and
        // they vouch differently — an admin looked at this number, or nobody
        // has. Rendering both as "administrator tasdiqlagan" would be the
        // silent degradation the rule exists to stop.
        when (state.verificationMethod) {
            NumberVerification.Method.ADMIN_ATTESTED -> Text(
                text = stringResource(R.string.enrol_done_attested),
                color = MaterialTheme.colorScheme.tertiary,
            )

            NumberVerification.Method.SELF_DECLARED -> Text(
                text = stringResource(R.string.enrol_done_self_declared),
                color = MaterialTheme.colorScheme.tertiary,
            )

            NumberVerification.Method.SIM_MSISDN,
            NumberVerification.Method.CALLBACK,
            null,
            -> Unit
        }

        Button(onClick = onFinish, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.common_continue))
        }

        TextButton(onClick = onOpenDiagnostics, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.enrol_done_diagnostics))
        }
    }
}
