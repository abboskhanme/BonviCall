package uz.bonvi.call.ui.enrolment

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import uz.bonvi.call.R
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityConsequence
import uz.bonvi.call.domain.CapabilityState
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E2 — permissions, in one request** (SPEC §8.2).
 *
 * ═══ What changed, and why ═════════════════════════════════════════════════
 * This screen used to walk nine capabilities one card at a time: tap, dialog,
 * check, next card, tap again — nine taps before anything else happened, on
 * the step of an unaided install where people already stop. Six of the nine
 * are ordinary runtime permissions, and Android shows those six dialogs back
 * to back from a single `RequestMultiplePermissions`. Same dialogs, same
 * order, **one tap to start them**.
 *
 * The three that are left are not dialogs at all — battery exemption,
 * all-files access, OEM autostart are settings screens — so they keep their
 * own buttons, and only while they are not already satisfied.
 *
 * ═══ The rule that did NOT change ══════════════════════════════════════════
 * **A row goes green only when the CAPABILITY works**, never because a dialog
 * was dismissed. `onPermissionsChecked` runs the real checks from SPEC §7.8 —
 * a one-second microphone capture, a one-row call-log query — and the chip
 * shows what each found. "Did you enable it?" with a checkbox is how a rollout
 * looks fine and captures nothing.
 *
 * Three outcomes, three different next actions, because they are three
 * different problems:
 *  • `denied` → the system dialog will help, so the button asks again;
 *  • `denied_permanently` → "Sozlamalardan yoqing" with a deep link;
 *  • `granted_not_working` → the OEM's own permission manager is blocking it,
 *    and **retrying the system dialog will never fix it**, so the screen says
 *    so instead of offering the same button again.
 */
@Composable
fun EnrolPermissionsScreen(viewModel: EnrolmentViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    val context = LocalContext.current
    val blocking = viewModel.blockingRequired()

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        // The RESULT map is deliberately ignored. What decides every row is the
        // capability check that follows, not what the dialogs reported — that
        // is the whole point of E2.
        viewModel.onPermissionsChecked()
    }

    LaunchedEffect(Unit) {
        // Check on entry, before asking for anything. A phone where the
        // permissions are already granted — a reinstall, a resumed enrolment —
        // walks straight through without a single dialog.
        viewModel.onPermissionsChecked()
    }

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_permissions_title),
        onStuck = viewModel::onStuck,
    ) {
        Text(stringResource(R.string.enrol_permissions_intro))

        if (state.checkingAll) {
            Text(stringResource(R.string.perm_check_running))
        }

        // ═══ One button, all six dialogs ═══════════════════════════════════
        Button(
            onClick = { launcher.launch(viewModel.runtimePermissions.toTypedArray()) },
            enabled = !state.checkingAll,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(stringResource(R.string.perm_allow_all))
        }

        // The list is a RESULT, not a queue. Every row is visible from the
        // start so the agent can see how long the step is, and each says what
        // the check found rather than what was tapped.
        viewModel.permissionOrder.forEach { capability ->
            CapabilityRow(
                capability = capability,
                result = state.capabilities[capability],
                checking = state.checking == capability,
                isSettingsScreen = capability in viewModel.settingsCapabilities,
                onOpenSettings = {
                    if (state.capabilities[capability]?.needsSettingsScreen == true) {
                        context.openAppSettings()
                    } else {
                        context.openSettingsFor(capability)
                    }
                },
                onRecheck = { viewModel.onPermissionStepFinished(capability) },
                onContinueWithout = { viewModel.onContinueWithout(capability) },
            )
        }

        // ⚠️ ALWAYS available. A screen whose own text says "retrying will not
        // fix this" must not also be the end of the road (UC-14): a phone that
        // logs calls without audio is a supported state, and refusing to enrol
        // it is strictly worse — an enrolled handset reporting BLOCKED is
        // visible to an admin, an unenrolled one is not. What it costs is
        // named above the control, so it is a decision and not an escape.
        if (blocking.isEmpty()) {
            Button(
                onClick = viewModel::onPermissionsDone,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.common_continue))
            }
        } else {
            Text(
                text = stringResource(R.string.perm_blocking_summary, blocking.size),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(
                onClick = viewModel::onPermissionsDone,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.perm_continue_without))
            }
        }
    }
}

/** One capability, and what the check actually found. */
@Composable
// `internal`, not private: the standalone "Ruxsatlar" screen draws the same
// rows. One row means one set of words and one definition of what green means
// — two would drift the day somebody fixes a state label in only one of them.
internal fun CapabilityRow(
    capability: Capability,
    result: uz.bonvi.call.domain.CapabilityResult?,
    checking: Boolean,
    isSettingsScreen: Boolean,
    onOpenSettings: () -> Unit,
    onRecheck: () -> Unit,
    onContinueWithout: () -> Unit,
    /** E2 offers "continue without"; the standalone Ruxsatlar screen is not a
     *  step, so there is nothing there to continue TO. */
    showContinueWithout: Boolean = true,
) {
    val working = result?.isWorking == true
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = stringResource(capability.titleRes()),
                    style = MaterialTheme.typography.titleMedium,
                )
                if (capability in CaptureReadiness.OPTIONAL) {
                    Text(
                        text = " (" + stringResource(R.string.common_optional) + ")",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            when {
                checking -> Text(stringResource(R.string.perm_check_running))
                result != null -> Text(
                    text = stringResource(result.state.labelRes()),
                    color = if (working) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        MaterialTheme.colorScheme.error
                    },
                )
            }

            // A satisfied row is a line of text and nothing else. Buttons on a
            // finished step are the noise that made this screen feel long.
            if (working) return@Column

            Text(stringResource(capability.purposeRes()))

            // `granted_not_working`: say why the obvious action will not work,
            // and send them where it will.
            if (result?.state == CapabilityState.GRANTED_NOT_WORKING) {
                Text(
                    text = stringResource(R.string.perm_state_not_working_help),
                    color = MaterialTheme.colorScheme.error,
                )
            }
            // What the check actually found — "1s test capture, 4800 samples,
            // peak 812". Evidence, not a verdict: "it did not work" with
            // nothing behind it is an unactionable call to the admin.
            result?.detail?.let {
                Text(text = it, style = MaterialTheme.typography.bodySmall)
            }

            // A settings screen for the three that are one, and for any runtime
            // permission the agent has denied permanently — where the system
            // dialog no longer appears at all.
            if (isSettingsScreen || result?.needsSettingsScreen == true) {
                Button(onClick = onOpenSettings, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.common_open_settings))
                }
                TextButton(onClick = onRecheck, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.perm_recheck))
                }
            }

            Text(
                text = stringResource(CapabilityConsequence.of(capability).costRes()),
                style = MaterialTheme.typography.bodySmall,
            )
            if (showContinueWithout) {
                TextButton(onClick = onContinueWithout) {
                    Text(
                        stringResource(
                            if (CapabilityConsequence.of(capability) == CapabilityConsequence.NONE) {
                                R.string.common_skip
                            } else {
                                R.string.perm_continue_without
                            },
                        ),
                    )
                }
            }
        }
    }
}

/** What continuing without this capability costs, in one Uzbek sentence. */
private fun CapabilityConsequence.costRes(): Int = when (this) {
    CapabilityConsequence.NONE -> R.string.perm_cost_none
    CapabilityConsequence.AUDIO_ONLY -> R.string.perm_cost_audio
    CapabilityConsequence.CAPTURE_BLOCKED -> R.string.perm_cost_blocked
}

internal fun Capability.titleRes(): Int = when (this) {
    Capability.PHONE_STATE -> R.string.perm_phone_state_title
    Capability.CALL_LOG -> R.string.perm_call_log_title
    Capability.NOTIFICATIONS -> R.string.perm_notifications_title
    Capability.MICROPHONE -> R.string.perm_microphone_title
    Capability.CALL_PHONE -> R.string.perm_call_phone_title
    Capability.CONTACTS -> R.string.perm_contacts_title
    Capability.BATTERY_EXEMPTION -> R.string.perm_battery_title
    Capability.STORAGE_ACCESS -> R.string.perm_storage_title
    Capability.OEM_AUTOSTART -> R.string.perm_autostart_title
    Capability.FOREGROUND_SERVICE, Capability.OEM_RECORDER, Capability.SUBSCRIPTION_RESOLUTION ->
        R.string.perm_phone_state_title
}

private fun Capability.purposeRes(): Int = when (this) {
    Capability.PHONE_STATE -> R.string.perm_phone_state_why
    Capability.CALL_LOG -> R.string.perm_call_log_why
    Capability.NOTIFICATIONS -> R.string.perm_notifications_why
    Capability.MICROPHONE -> R.string.perm_microphone_why
    Capability.CALL_PHONE -> R.string.perm_call_phone_why
    Capability.CONTACTS -> R.string.perm_contacts_why
    Capability.BATTERY_EXEMPTION -> R.string.perm_battery_why
    Capability.STORAGE_ACCESS -> R.string.perm_storage_why
    Capability.OEM_AUTOSTART -> R.string.perm_autostart_why
    Capability.FOREGROUND_SERVICE, Capability.OEM_RECORDER, Capability.SUBSCRIPTION_RESOLUTION ->
        R.string.perm_phone_state_why
}

private fun CapabilityState.labelRes(): Int = when (this) {
    CapabilityState.GRANTED_WORKING -> R.string.perm_state_working
    CapabilityState.GRANTED_NOT_WORKING -> R.string.perm_state_not_working
    CapabilityState.DENIED -> R.string.perm_state_denied
    CapabilityState.DENIED_PERMANENTLY -> R.string.perm_state_denied_permanently
    CapabilityState.NOT_APPLICABLE, CapabilityState.UNKNOWN -> R.string.perm_state_unknown
}
