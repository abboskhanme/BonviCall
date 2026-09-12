package uz.bonvi.call.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.bonvi.call.R
import uz.bonvi.call.domain.DeviceAuthState
import uz.bonvi.call.ui.enrolment.NumberBanner
import uz.bonvi.call.ui.enrolment.collectAsStateWithLifecycleCompat

/**
 * The screen an enrolled phone opens on (N41, T76).
 *
 * Three questions in the order the person carrying the phone asks them: which
 * number is recorded, is it working, and what is waiting to be sent. Then the
 * two places they can go — their own calls, and the state screen an admin asks
 * them to read out during a support call.
 *
 * **"Qayd etilmoqda" appears only when capture is actually running.** When it
 * is not, the screen names the reason instead: an app that claims to be
 * recording while it is not is how a rollout looks finished and produces
 * nothing, and it is the failure this whole product is built against.
 */
@Composable
fun HomeScreen(
    viewModel: HomeViewModel = hiltViewModel(),
    onOpenCalls: () -> Unit = {},
    onOpenDiagnostics: () -> Unit = {},
    /** Only offered to a revoked handset: the admin retired this installation,
     *  and a new code — from a link or read out over the phone — is how the
     *  same person carries on working (UC-07, UC-08). */
    onReEnrol: () -> Unit = {},
) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()

    // The OS can stop the service while this screen is in the background, so
    // the answer is re-read on entry rather than remembered.
    LaunchedEffect(Unit) { viewModel.refresh() }

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
                    text = stringResource(R.string.home_title),
                    style = MaterialTheme.typography.headlineSmall,
                )
                state.agentName?.let { Text(stringResource(R.string.enrol_hello, it)) }

                Text(
                    text = stringResource(
                        if (state.capturing) R.string.diag_capturing else R.string.diag_not_capturing,
                    ),
                    style = MaterialTheme.typography.titleLarge,
                    color = if (state.capturing) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        MaterialTheme.colorScheme.error
                    },
                )

                // Why not — one sentence per cause, because they lead to three
                // different next actions and "not working" leads to none.
                when {
                    !state.enrolled -> Text(stringResource(R.string.enrol_not_finished))

                    state.authState == DeviceAuthState.REVOKED ->
                        Text(stringResource(R.string.home_revoked))

                    state.authState == DeviceAuthState.AUTH_EXPIRED ->
                        Text(stringResource(R.string.home_auth_expired))

                    state.authState == DeviceAuthState.UPDATE_REQUIRED ->
                        Text(stringResource(R.string.home_update_required))

                    !state.serviceRunning -> Text(stringResource(R.string.home_service_off))
                }

                Text(
                    text = stringResource(
                        if (state.serviceRunning) R.string.diag_service else R.string.diag_service_off,
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                )

                // The queue is never discarded, in any state (N25). Somebody
                // looking at a phone that has stopped sending needs to read
                // that here rather than be told it later.
                if (state.hasBacklog) {
                    Text(stringResource(R.string.diag_queue, state.pending))
                    if (state.parked > 0) {
                        Text(stringResource(R.string.diag_queue_parked, state.parked))
                    }
                    Text(stringResource(R.string.home_queue_safe))
                }

                if (state.authState == DeviceAuthState.REVOKED) {
                    Button(onClick = onReEnrol, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.home_re_enrol))
                    }
                }

                Button(onClick = onOpenCalls, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.home_my_calls))
                }

                TextButton(onClick = onOpenDiagnostics, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.enrol_done_diagnostics))
                }
            }
        }
    }
}
