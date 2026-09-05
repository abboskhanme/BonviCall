package uz.bonvi.call.ui.diagnostics

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.bonvi.call.R
import uz.bonvi.call.data.repository.ServerAddressRepository
import uz.bonvi.call.domain.ServerAddress
import uz.bonvi.call.ui.enrolment.NumberBanner
import uz.bonvi.call.ui.enrolment.collectAsStateWithLifecycleCompat

/**
 * "Ilova holati" (UC-07, N41).
 *
 * The screen an admin asks an agent to read out during an assisted install, and
 * the one `docs/QOLLANMA.md` sends them to. It leads with the N41 banner —
 * which number is recorded — because that is the question the employee has,
 * and only then answers the one the admin has.
 *
 * The server-address section is **debug builds only**. It is not merely
 * hidden: `SessionStore.saveBaseUrl` refuses a manual write in a release build,
 * so a screen that somehow rendered it could still not repoint the phone.
 * Hiding a control is not access control.
 */
@Composable
fun DiagnosticsScreen(viewModel: DiagnosticsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            NumberBanner(state.registeredNumber)
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    text = stringResource(R.string.diagnostics_title),
                    style = MaterialTheme.typography.headlineSmall,
                )

                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(
                            text = stringResource(
                                if (state.capturing) R.string.diag_capturing
                                else R.string.diag_not_capturing,
                            ),
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Text(
                            stringResource(
                                if (state.serviceRunning) R.string.diag_service
                                else R.string.diag_service_off,
                            ),
                        )
                        // Records, not bytes: the person reading this out loud
                        // needs a number they can say.
                        Text(stringResource(R.string.diag_queue, state.pending))
                        if (state.parked > 0) {
                            Text(
                                text = stringResource(R.string.diag_queue_parked, state.parked),
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                        Text(stringResource(R.string.diag_app_version, state.appVersion))
                        Text(state.variant)
                    }
                }

                if (state.serverEditable) ServerAddressSection(state, viewModel)
            }
        }
    }
}

/**
 * Debug only. A free tunnel gets a new hostname every restart, and baking the
 * address into the APK turned a five-second problem into a rebuild, a file
 * transfer and a reinstall.
 *
 * **Check before save**, and save is disabled until the check passes: an
 * unreachable address saved is a phone pointed at nothing, and every failure
 * after that reads as "no internet".
 */
@Composable
private fun ServerAddressSection(
    state: DiagnosticsViewModel.UiState,
    viewModel: DiagnosticsViewModel,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = stringResource(R.string.diag_server_title),
                style = MaterialTheme.typography.titleMedium,
            )

            OutlinedTextField(
                value = state.serverAddress,
                onValueChange = viewModel::onServerAddressChanged,
                placeholder = { Text(stringResource(R.string.diag_server_hint)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done,
                ),
                modifier = Modifier.fillMaxWidth(),
            )

            state.serverCheck?.let { result ->
                val (textRes, isError) = when (result) {
                    is ServerAddressRepository.CheckResult.Reachable ->
                        R.string.diag_server_ok to false

                    is ServerAddressRepository.CheckResult.Unreachable ->
                        R.string.diag_server_unreachable to true

                    is ServerAddressRepository.CheckResult.NotBonviCall ->
                        R.string.diag_server_not_bonvicall to true

                    is ServerAddressRepository.CheckResult.Invalid -> when (result.reason) {
                        ServerAddress.Validation.Reason.NO_HOST ->
                            R.string.diag_server_no_host to true

                        else -> R.string.diag_server_bad_url to true
                    }
                }
                Text(
                    text = if (result is ServerAddressRepository.CheckResult.NotBonviCall) {
                        stringResource(textRes, result.status)
                    } else {
                        stringResource(textRes)
                    },
                    color = if (isError) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }

            // The exception class, verbatim. A developer reading this over the
            // phone needs the word the network used, not a paraphrase of it.
            state.serverCheckDetail?.let {
                Text(text = it, style = MaterialTheme.typography.bodySmall)
            }

            if (state.serverSaved) Text(stringResource(R.string.diag_server_saved))

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.checking) {
                    CircularProgressIndicator()
                } else {
                    Button(onClick = viewModel::onCheckServer) {
                        Text(stringResource(R.string.diag_server_check))
                    }
                }
                Button(
                    onClick = viewModel::onSaveServer,
                    // Save only after the address has actually answered.
                    enabled = viewModel.canSave(),
                ) {
                    Text(stringResource(R.string.diag_server_save))
                }
            }
        }
    }
}
