package uz.bonvi.call.ui.calls

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.material3.LocalContentColor
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import uz.bonvi.call.R
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.AudioPlayback
import uz.bonvi.call.domain.AudioState
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
    val playback by viewModel.playback.collectAsStateWithLifecycleCompat()

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
                    items(state.calls, key = { it.id }) { call ->
                        CallRow(
                            call = call,
                            // Only the row being played reads the progress, so
                            // a slider moving five times a second recomposes
                            // one card rather than the list.
                            progress = playback.takeIf { it.callId == call.id },
                            onPlay = viewModel::play,
                            onPause = viewModel::pause,
                            onSeek = viewModel::seekTo,
                        )
                    }
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

/**
 * One call, as the person who made it reads it.
 *
 * ═══ What the row leads with, and why ══════════════════════════════════════
 * The NAME where the phone resolved one at capture time (T139) and the number
 * underneath it — not one or the other. The name alone is unusable when two
 * people share a name in a contact list; the number alone is what the row used
 * to show for every contact the phone could not match, and an employee
 * scanning for "the call with Anvar" was reading twelve digits at a time.
 *
 * Then the facts in one line: which way the call went, when it started, and
 * how long it lasted.
 */
@Composable
private fun CallRow(
    call: MyCall,
    progress: AudioPlayback.Progress?,
    onPlay: (MyCall) -> Unit,
    onPause: () -> Unit,
    onSeek: (Long) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            val name = call.contactName
            Text(
                text = name ?: call.remoteNumber.orEmpty(),
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            // The number sits under the name only when a name was found —
            // repeating it as its own subtitle would read as two numbers.
            if (name != null && !call.remoteNumber.isNullOrBlank()) {
                Text(
                    text = call.remoteNumber,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(top = 4.dp),
            ) {
                DirectionChip(call.direction)
                Text(
                    text = TIME.format(Date(call.startedAtEpochMillis)),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = stringResource(
                        R.string.calls_duration,
                        call.durationSec / 60,
                        call.durationSec % 60,
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            AudioRow(call, progress, onPlay, onPause, onSeek)
        }
    }
}

/** Kiruvchi / Chiquvchi, as a chip rather than a word in a row of words. */
@Composable
private fun DirectionChip(direction: CallDirection) {
    val incoming = direction == CallDirection.INCOMING
    Surface(
        color = if (incoming) {
            MaterialTheme.colorScheme.secondaryContainer
        } else {
            MaterialTheme.colorScheme.tertiaryContainer
        },
        shape = MaterialTheme.shapes.small,
    ) {
        Text(
            text = stringResource(
                if (incoming) R.string.calls_incoming else R.string.calls_outgoing,
            ),
            style = MaterialTheme.typography.labelSmall,
            color = if (incoming) {
                MaterialTheme.colorScheme.onSecondaryContainer
            } else {
                MaterialTheme.colorScheme.onTertiaryContainer
            },
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
        )
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
 * What the employee sees where the audio is, or is not.
 *
 * ═══ `audio_state` decides, and every arm has its sentence ═════════════════
 * **`EXPIRED` is not a failure and must not read like one**: the recording
 * existed and retention removed it, which is the system working as designed.
 * `QUEUED` says it is on the way. `NOT_EXPECTED` says there was no
 * conversation. Only `MISSING` carries a reason, and that is where the
 * ten-value enum earns its place.
 *
 * A play control appears **only** for `RECORDED`. A button that answers 410
 * teaches somebody the app is broken when it is behaving exactly as designed.
 */
@Composable
private fun AudioRow(
    call: MyCall,
    progress: AudioPlayback.Progress?,
    onPlay: (MyCall) -> Unit,
    onPause: () -> Unit,
    onSeek: (Long) -> Unit,
) {
    when (call.audioState) {
        AudioState.RECORDED -> Player(call, progress, onPlay, onPause, onSeek)

        AudioState.EXPIRED -> Muted(stringResource(R.string.audio_expired))
        AudioState.QUEUED -> Muted(stringResource(R.string.audio_queued))
        AudioState.NOT_EXPECTED -> Muted(stringResource(R.string.audio_not_expected))

        AudioState.MISSING -> Muted(
            // The reason is guaranteed present for MISSING, and the fallback is
            // the honest one rather than a blank line if the server ever sends
            // MISSING without one.
            stringResource(
                call.audioMissingReason?.labelRes()
                    ?: R.string.reason_recording_route_unavailable,
            ),
        )
    }
}

/**
 * The player: a control, a position, and the two numbers that make it legible.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * It was one `TextButton` whose label flipped between "Tinglash" and
 * "To'xtatish". Sound came out of the phone and nothing else was knowable —
 * not how long the recording is, not where in it the playback had reached, not
 * whether it had ended or stalled. "What did I promise at the end of that
 * call" meant listening to the whole call again.
 *
 * So the row draws what a player is: play/pause, a **seekable** bar, and
 * `position / duration`. Seeking is real — ExoPlayer issues a `Range` request
 * for the new offset (N43), so dragging to the last minute of a twenty-minute
 * call fetches that minute rather than the twenty.
 *
 * The bar appears only on the row being played. A slider on every row would
 * suggest twelve recordings are loaded when one is, and only one can be: the
 * player holds a single codec, and two conversations out loud at once is
 * nobody's intention.
 * ═══════════════════════════════════════════════════════════════════════════
 */
@Composable
private fun Player(
    call: MyCall,
    progress: AudioPlayback.Progress?,
    onPlay: (MyCall) -> Unit,
    onPause: () -> Unit,
    onSeek: (Long) -> Unit,
) {
    val loaded = progress != null
    val playing = progress?.playing == true

    // While the thumb is held, the bar follows the FINGER and not the player:
    // a slider that keeps jumping back to the playhead cannot be dragged.
    var scrubbing by remember(call.id) { mutableStateOf<Float?>(null) }
    val fraction = scrubbing ?: progress?.fraction ?: 0f
    val durationMs = progress?.durationMs ?: (call.durationSec * 1000L)

    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
    ) {
        FilledTonalIconButton(
            onClick = { if (playing) onPause() else onPlay(call) },
        ) {
            // TalkBack reads what the control does NOW, not what it is called.
            val label = stringResource(if (playing) R.string.calls_pause else R.string.calls_play)
            if (playing) {
                PauseGlyph(label)
            } else {
                Icon(imageVector = Icons.Filled.PlayArrow, contentDescription = label)
            }
        }

        if (loaded) {
            Slider(
                value = fraction,
                onValueChange = { scrubbing = it },
                onValueChangeFinished = {
                    scrubbing?.let { onSeek((it * durationMs).toLong()) }
                    scrubbing = null
                },
                modifier = Modifier.weight(1f),
            )
            Text(
                text = "${clock(fraction * durationMs)} / ${clock(durationMs.toFloat())}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            // Not loaded yet: the label is the invitation, and the duration is
            // already known from the call itself.
            Text(
                text = stringResource(R.string.calls_play),
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.weight(1f),
            )
            Text(
                text = clock(durationMs.toFloat()),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Two bars, drawn rather than imported.
 *
 * `Icons.Filled.Pause` lives in `material-icons-extended`, and adding that
 * dependency to ship one glyph would put every Material icon on the phones of
 * fifteen people whose data allowance pays for the APK. This is the icon.
 */
@Composable
private fun PauseGlyph(label: String) {
    val colour = LocalContentColor.current
    Canvas(modifier = Modifier.size(20.dp).semantics { contentDescription = label }) {
        val barWidth = size.width * 0.28f
        val gap = size.width * 0.16f
        val height = size.height * 0.78f
        val top = (size.height - height) / 2
        val left = (size.width - (barWidth * 2 + gap)) / 2
        drawRoundRect(
            color = colour,
            topLeft = Offset(left, top),
            size = Size(barWidth, height),
            cornerRadius = CornerRadius(barWidth / 3),
        )
        drawRoundRect(
            color = colour,
            topLeft = Offset(left + barWidth + gap, top),
            size = Size(barWidth, height),
            cornerRadius = CornerRadius(barWidth / 3),
        )
    }
}

/** `07:24`. Minutes past an hour keep counting — a 70-minute call reads 70:12
 *  rather than starting again at 10:12. */
private fun clock(millis: Float): String {
    val total = (millis / 1000).toLong().coerceAtLeast(0)
    return "%02d:%02d".format(Locale.US, total / 60, total % 60)
}

@Composable
private fun Muted(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
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
