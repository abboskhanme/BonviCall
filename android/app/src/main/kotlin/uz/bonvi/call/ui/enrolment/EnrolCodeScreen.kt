package uz.bonvi.call.ui.enrolment

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.foundation.text.KeyboardOptions
import uz.bonvi.call.R
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E1 — the enrolment code** (SPEC §8.2).
 *
 * Prefilled from the `bonvicall://enrol?code=…` deep link, so on the happy path
 * nobody types anything: the landing page's button opens this screen with the
 * code already in the field. It is still editable, because a deep link that did
 * not survive the browser is not a reason to restart the whole install.
 *
 * On success the screen shows the agent's name and the number being registered
 * — the first time the app itself says what the landing page promised (N41).
 *
 * ⚠️ Success here is NOT "done". Redeeming returns a **provisional** token; the
 * real pair arrives only after the number is proven, and until then the server
 * accepts no calls. The flow therefore moves straight to E2 and the word
 * "tayyor" appears nowhere on this screen.
 */
@Composable
fun EnrolCodeScreen(
    viewModel: EnrolmentViewModel,
    prefilledCode: String? = null,
    /**
     * "Yordam kerak" on E1 must also OPEN the diagnostics screen, not only
     * report the stall.
     *
     * E1 is where a wrong or dead server address surfaces, and the screen that
     * fixes it was reachable only from E6 — so the one control that repairs a
     * broken connection sat behind having a working one. A real handset hit
     * that twice today: a correct build, an unreachable address, and no way
     * from the failing screen to the field that sets it.
     */
    onOpenDiagnostics: () -> Unit = {},
) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    var code by remember { mutableStateOf(prefilledCode.orEmpty()) }

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_code_title),
        onStuck = {
            // Both: the admin needs to know somebody is stuck, and the person
            // stuck needs the screen that shows what is wrong.
            viewModel.onStuck()
            onOpenDiagnostics()
        },
    ) {
        state.agentName?.let { Text(stringResource(R.string.enrol_hello, it)) }
        Text(stringResource(R.string.enrol_code_explain))

        // The server this build talks to, on the screen where enrolment fails.
        // The first handset this app was ever installed on reported "no
        // internet" while its browser reached the server fine, and nothing on
        // the device could say which address it was even using.
        Text(
            text = "${uz.bonvi.call.BuildConfig.DEFAULT_BASE_URL}  ·  ${uz.bonvi.call.BuildConfig.BUILD_STAMP}",
            style = androidx.compose.material3.MaterialTheme.typography.bodySmall,
        )

        // Debug builds only. The user-facing message stays one calm sentence;
        // a tester gets the exception that produced it.
        state.debugDetail?.let {
            Text(
                text = it,
                style = androidx.compose.material3.MaterialTheme.typography.bodySmall,
            )
        }

        OutlinedTextField(
            value = code,
            onValueChange = { code = it },
            label = { Text(stringResource(R.string.enrol_code_hint)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(
                // The codes are upper-case alphanumerics. Auto-capitalising
                // removes one of the two things a person can get wrong here.
                capitalization = KeyboardCapitalization.Characters,
                imeAction = ImeAction.Done,
            ),
            modifier = Modifier.fillMaxWidth(),
        )

        state.message?.let { message ->
            Text(
                text = stringResource(message.textRes),
                color = MaterialTheme.colorScheme.error,
            )
            message.actionRes?.let { actionRes ->
                TextButton(onClick = { viewModel.onCodeEntered(code) }) {
                    Text(stringResource(actionRes))
                }
            }
        }

        if (state.busy) {
            CircularProgressIndicator()
        } else {
            Button(
                onClick = { viewModel.onCodeEntered(code) },
                enabled = code.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.enrol_code_submit))
            }
        }
    }
}
