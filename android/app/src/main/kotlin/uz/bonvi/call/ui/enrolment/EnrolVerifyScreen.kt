package uz.bonvi.call.ui.enrolment

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import kotlinx.coroutines.delay
import uz.bonvi.call.R
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E5 — proving the number** (SPEC §8.2, §9).
 *
 * Route 1 (the SIM's own MSISDN) runs **automatically and invisibly**. If it
 * cannot prove the match — which is the common case on Uzbek SIMs, because
 * `getLine1Number()` is simply empty — this screen becomes route 2: the
 * receiver's number in large type, a button that dials it, a five-minute
 * countdown, and live status.
 *
 * **The agent is never told the app "checked the SIM and failed".** They are
 * told what to do next. A person on their own phone, five minutes into an
 * install, does not need to know which of two mechanisms the app tried.
 *
 * The call is not answered — ringing is enough — so nobody is charged and no
 * audio exists.
 */
@Composable
fun EnrolVerifyScreen(
    viewModel: EnrolmentViewModel,
    line1Number: String?,
    carrierName: String?,
    simSlot: Int?,
) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        viewModel.onVerifyStarted(line1Number, carrierName, simSlot)
    }

    // Poll while the window is open. The server tells us how often; the
    // countdown is what the agent sees.
    val challenge = state.callback
    LaunchedEffect(challenge?.verificationId) {
        val active = challenge ?: return@LaunchedEffect
        var remaining = state.secondsLeft
        while (remaining > 0) {
            delay(active.pollAfterMs.toLong())
            viewModel.onPollCallback()
            remaining -= (active.pollAfterMs / 1000).coerceAtLeast(1)
            viewModel.onCallbackTick(remaining)
        }
    }

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_verify_title),
        onStuck = viewModel::onStuck,
    ) {
        if (state.busy && challenge == null) {
            // Route 1 is running. Deliberately no text about "checking the
            // SIM": if it fails, the next thing on screen is an instruction,
            // not an explanation of a mechanism.
            CircularProgressIndicator()
            return@EnrolScaffold
        }

        challenge?.let {
            Text(stringResource(R.string.enrol_verify_explain))
            Text(text = it.callbackMsisdn, style = MaterialTheme.typography.headlineMedium)
            Button(
                onClick = {
                    context.startActivity(
                        Intent(Intent.ACTION_DIAL, Uri.parse("tel:${it.callbackMsisdn}"))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.enrol_verify_call))
            }
            Text(
                stringResource(
                    R.string.enrol_verify_waiting,
                    "%d:%02d".format(state.secondsLeft / 60, state.secondsLeft % 60),
                ),
            )
        }

        state.message?.let { message ->
            Text(
                text = stringResource(message.textRes),
                color = MaterialTheme.colorScheme.error,
            )
            message.actionRes?.let { actionRes ->
                TextButton(
                    onClick = {
                        // R19: on `no_caller_id` the only way forward is a
                        // person, so "retry" would be a lie. `onStuck` moves
                        // the agent to needs_assisted_install in the panel.
                        if (message.action == EnrolmentViewModel.UiMessage.Action.CONTACT_ADMIN) {
                            viewModel.onStuck()
                        } else {
                            viewModel.onVerifyStarted(line1Number, carrierName, simSlot)
                        }
                    },
                ) {
                    Text(stringResource(actionRes))
                }
            }
        }
    }
}
