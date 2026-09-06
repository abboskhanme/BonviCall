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
import uz.bonvi.call.domain.CapabilityState
import uz.bonvi.call.domain.CapabilityConsequence
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.domain.runtimePermission
import uz.bonvi.call.enrolment.EnrolmentViewModel

/**
 * **E2 — permissions, one at a time** (SPEC §8.2).
 *
 * Exactly one row is expanded. Each row carries one Uzbek sentence of PURPOSE
 * AND CONSEQUENCE — "Mikrofon bo'lmasa suhbat yozilmaydi, lekin qo'ng'iroq
 * baribir qayd etiladi" — a single button, and a live result chip.
 *
 * ═══ The row turns green only when the CAPABILITY works ════════════════════
 * Not when the dialog was dismissed. `viewModel.onPermissionStepFinished` runs
 * the real check from SPEC §7.8 — a one-second microphone capture, a one-row
 * call-log query — and the chip shows what it found. "Did you enable it?" with
 * a checkbox is how a rollout looks fine and captures nothing.
 *
 * Three outcomes, three different next actions, because they are three
 * different problems:
 *  • `denied` → the system dialog will help;
 *  • `denied_permanently` → "Sozlamalardan yoqing" with a deep link;
 *  • `granted_not_working` → the OEM's own permission manager is blocking it,
 *    and **retrying the system dialog will never fix it**, so the screen says
 *    so instead of offering the same button again.
 *
 * The order is SPEC's: the alarming permissions come after two easy successes.
 */
@Composable
fun EnrolPermissionsScreen(viewModel: EnrolmentViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    val context = LocalContext.current
    val order = viewModel.permissionOrder
    val current = order.getOrNull(state.currentPermissionIndex)

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        // The RESULT of the dialog is deliberately ignored. What decides the
        // row is the capability check that follows, not what the dialog
        // reported — that is the whole point of E2.
        current?.let(viewModel::onPermissionStepFinished)
    }

    LaunchedEffect(current) {
        // Re-check on entry: a permission granted in a previous run, or granted
        // from the settings screen and returned from, must not need a tap.
        current?.let(viewModel::onPermissionStepFinished)
    }

    EnrolScaffold(
        number = state.registeredNumber,
        title = stringResource(R.string.enrol_permissions_title),
        onStuck = viewModel::onStuck,
    ) {
        order.forEachIndexed { index, capability ->
            val result = state.capabilities[capability]
            val expanded = index == state.currentPermissionIndex
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

                    if (state.checking == capability) {
                        Text(stringResource(R.string.perm_check_running))
                    } else {
                        result?.let { Text(text = stringResource(it.state.labelRes())) }
                    }

                    if (!expanded) return@Column

                    Text(stringResource(capability.purposeRes()))

                    // `granted_not_working`: say why the obvious action will not
                    // work, and send them where it will.
                    if (result?.state == CapabilityState.GRANTED_NOT_WORKING) {
                        Text(
                            text = stringResource(R.string.perm_state_not_working_help),
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    // What the check actually found — "1s test capture, 4800
                    // samples, peak 812". Evidence, not a verdict: "it did not
                    // work" with nothing behind it is an unactionable call to
                    // the admin.
                    result?.detail?.let {
                        Text(text = it, style = MaterialTheme.typography.bodySmall)
                    }

                    val permission = capability.runtimePermission()
                    Button(
                        onClick = {
                            when {
                                result?.needsSettingsScreen == true ->
                                    context.openAppSettings()
                                permission != null -> launcher.launch(permission)
                                else -> context.openSettingsFor(capability)
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            stringResource(
                                if (result?.needsSettingsScreen == true) {
                                    R.string.common_open_settings
                                } else {
                                    R.string.perm_allow
                                },
                            ),
                        )
                    }

                    // ⚠️ ALWAYS available, for every capability. A step whose
                    // own text says "retrying will not fix this" must not also
                    // be the end of the road (UC-14). The cost is named above
                    // the control, so this is a decision rather than an escape.
                    val consequence = CapabilityConsequence.of(capability)
                    val alreadyWorking = result?.isWorking == true
                    if (!alreadyWorking) {
                        Text(
                            text = stringResource(consequence.costRes()),
                            style = MaterialTheme.typography.bodySmall,
                        )
                        TextButton(onClick = { viewModel.onContinueWithout(capability) }) {
                            Text(
                                stringResource(
                                    if (consequence == CapabilityConsequence.NONE) {
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
