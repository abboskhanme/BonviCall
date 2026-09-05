package uz.bonvi.call.ui.diagnostics

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.bonvi.call.diagnostics.DiagnosticsViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import uz.bonvi.call.R

/**
 * Queue depth, last contact, capability states, capture route — this is what an
 * admin asks the employee to read out during an assisted install (UC-07).
 *
 * The **server address** leads, and it leads for a reason learned on the first
 * real handset: the app said "no internet" while the phone's browser reached
 * the server without trouble. Nothing on the device could answer "which server
 * are you even asking?", so a one-line configuration mistake looked like a
 * network fault. Any device that cannot state what it is talking to costs
 * somebody an afternoon.
 */
@Composable
fun DiagnosticsScreen(viewModel: DiagnosticsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.refresh() }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = stringResource(R.string.diagnostics_title),
                style = MaterialTheme.typography.headlineSmall,
            )

            Row(stringResource(R.string.diagnostics_server), state.baseUrl)

            when (state.reach) {
                DiagnosticsViewModel.Reach.OK ->
                    Text(
                        text = stringResource(R.string.diagnostics_reach_ok),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                DiagnosticsViewModel.Reach.FAILED ->
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(
                            text = stringResource(R.string.diagnostics_reach_failed),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        // The raw exception, deliberately. "Connection failed"
                        // sends nobody anywhere; the class name distinguishes a
                        // cleartext policy from an unreachable host, and those
                        // have different fixes.
                        state.reachDetail?.let {
                            Text(text = it, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                DiagnosticsViewModel.Reach.CHECKING ->
                    Text(
                        text = stringResource(R.string.diagnostics_reach_checking),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                DiagnosticsViewModel.Reach.UNKNOWN -> Unit
            }

            Button(
                onClick = viewModel::testConnection,
                enabled = state.reach != DiagnosticsViewModel.Reach.CHECKING,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.diagnostics_test))
            }

            HorizontalDivider()

            Row(stringResource(R.string.diagnostics_version), "${state.appVersion} · ${state.variant}")
            Row(
                stringResource(R.string.diagnostics_enrolled),
                stringResource(
                    if (state.enrolled) R.string.diagnostics_enrolled_yes
                    else R.string.diagnostics_enrolled_no,
                ),
            )
            state.registeredNumber?.let {
                Row(stringResource(R.string.diagnostics_number), it)
            }
        }
    }
}

@Composable
private fun Row(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(text = label, style = MaterialTheme.typography.labelMedium)
        Text(text = value, style = MaterialTheme.typography.bodyLarge)
    }
}
