package uz.bonvi.call.ui.calls

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.bonvi.call.R
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.MyCall
import uz.bonvi.call.ui.enrolment.NumberBanner
import uz.bonvi.call.ui.enrolment.collectAsStateWithLifecycleCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The employee's own calls (client request, N41).
 *
 * *"telefonda o'rnatiladigan appda ham shu xodim o'zining callarini ko'rishi va
 * eshitishi mumkin bo'lsin — bizni tizimga kirib o'tirmaydi."* A salesperson
 * should not need a panel login to see their own work.
 *
 * `docs/QOLLANMA.md` promises the employee transparency about what is
 * recorded. This screen is that promise: it opens with the N41 banner — which
 * number — and then shows what the company actually holds against it.
 *
 * **Every row says whether there is a recording, and if not, why.** That is
 * where an employee learns the difference the whole product rests on: a call is
 * always *qayd etilgan* (logged) and only sometimes *yozib olingan* (recorded).
 * A row with no audio and no reason would leave them to guess, and guessing is
 * what the gap report exists to stop an admin doing.
 */
@Composable
fun MyCallsScreen(viewModel: MyCallsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            NumberBanner(state.registeredNumber)

            when {
                state.loading && state.calls.isEmpty() ->
                    Centre { CircularProgressIndicator() }

                state.message != null -> Centre {
                    Text(
                        text = stringResource(
                            when (state.message) {
                                MyCallsViewModel.Message.NOT_AVAILABLE ->
                                    R.string.calls_not_available
                                MyCallsViewModel.Message.OFFLINE -> R.string.calls_offline
                                else -> R.string.calls_error
                            },
                        ),
                        style = MaterialTheme.typography.bodyLarge,
                    )
                }

                state.isEmpty -> Centre { Text(stringResource(R.string.calls_empty)) }

                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.calls, key = { it.id }) { CallRow(it) }
                    if (state.hasMore) {
                        item {
                            TextButton(
                                onClick = viewModel::loadMore,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(stringResource(R.string.calls_load_more))
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CallRow(call: MyCall) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            // The name where one resolved (T139), the number otherwise. Never
            // both, and never a placeholder that looks like a missing name.
            Text(
                text = call.contactName ?: call.remoteNumber.orEmpty(),
                style = MaterialTheme.typography.titleMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    stringResource(
                        if (call.direction == CallDirection.INCOMING) {
                            R.string.calls_incoming
                        } else {
                            R.string.calls_outgoing
                        },
                    ),
                )
                Text(TIME.format(Date(call.startedAtEpochMillis)))
                Text(
                    stringResource(
                        R.string.calls_duration,
                        call.durationSec / 60,
                        call.durationSec % 60,
                    ),
                )
            }

            // Audio, or the honest reason. Never a dead play button.
            if (call.playable) {
                TextButton(onClick = { /* T-audio-playback */ }) {
                    Text(stringResource(R.string.calls_play))
                }
            } else {
                Text(
                    text = stringResource(call.audioMissingReason.labelRes()),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun Centre(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally,
    ) { content() }
}

/**
 * One Uzbek sentence per reason — all ten of them.
 *
 * `when` over the enum with no `else`, so a value added to the closed set is a
 * compile error rather than a blank line on somebody's screen.
 */
private fun AudioMissingReason.labelRes(): Int = when (this) {
    AudioMissingReason.PENDING_UPLOAD -> R.string.reason_pending_upload
    AudioMissingReason.NOT_EXPECTED -> R.string.reason_not_expected
    AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE -> R.string.reason_recording_route_unavailable
    AudioMissingReason.OEM_RECORDER_OFF -> R.string.reason_oem_recorder_off
    AudioMissingReason.NO_PERMISSION -> R.string.reason_no_permission
    AudioMissingReason.CAPTURE_RETURNED_SILENCE -> R.string.reason_capture_returned_silence
    AudioMissingReason.APP_NOT_RUNNING -> R.string.reason_app_not_running
    AudioMissingReason.UPLOAD_EXPIRED -> R.string.reason_upload_expired
    AudioMissingReason.QUEUE_SPACE_EXHAUSTED -> R.string.reason_queue_space_exhausted
    AudioMissingReason.ATTRIBUTION_FAILED -> R.string.reason_attribution_failed
}

private val TIME = SimpleDateFormat("dd.MM HH:mm", Locale("uz"))
