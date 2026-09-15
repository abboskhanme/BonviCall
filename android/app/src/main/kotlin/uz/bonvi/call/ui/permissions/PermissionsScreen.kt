package uz.bonvi.call.ui.permissions

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import uz.bonvi.call.R
import uz.bonvi.call.ui.enrolment.CapabilityRow
import uz.bonvi.call.ui.enrolment.collectAsStateWithLifecycleCompat
import uz.bonvi.call.ui.enrolment.openAppSettings
import uz.bonvi.call.ui.enrolment.openSettingsFor

/**
 * "Ruxsatlar" (client request, 2026-09-15).
 *
 * ═══ Why it re-checks on RESUME and not only on entry ══════════════════════
 * Three of the nine are not dialogs: battery exemption, all-files access and
 * OEM autostart are settings screens in another app. Granting one means
 * leaving this screen and coming back — so the moment the answer changes is
 * exactly the moment this screen is resumed, and a check that ran only on
 * entry would show the old answer to the person who had just fixed it.
 *
 * That was not hypothetical: on 2026-09-15 a handset recorded four calls as
 * pure silence because all-files access had been skipped, and after it was
 * granted, both the app and the panel went on saying it was missing.
 */
@Composable
fun PermissionsScreen(viewModel: PermissionsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycleCompat()
    val context = LocalContext.current

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) {
        // The RESULT map is ignored on purpose, exactly as in E2: what decides
        // a row is the capability check that follows, never what the dialog
        // reported (SPEC §7.8).
        viewModel.recheck()
    }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) viewModel.recheck()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = stringResource(R.string.permissions_title),
                style = MaterialTheme.typography.headlineSmall,
            )

            // The headline answer first: a screen of nine rows with no summary
            // makes the reader do the counting.
            Text(
                text = when {
                    !state.checked || state.checking -> stringResource(R.string.perm_check_running)
                    state.blocking.isEmpty() -> stringResource(R.string.permissions_all_good)
                    else -> stringResource(R.string.perm_blocking_summary, state.blocking.size)
                },
                color = if (state.checked && state.blocking.isNotEmpty()) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
            )
            Text(
                text = stringResource(R.string.permissions_intro),
                style = MaterialTheme.typography.bodyMedium,
            )

            Button(
                onClick = { launcher.launch(viewModel.runtimePermissions.toTypedArray()) },
                enabled = !state.checking,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.perm_allow_all))
            }

            viewModel.order.forEach { capability ->
                CapabilityRow(
                    capability = capability,
                    result = state.capabilities[capability],
                    checking = state.checking,
                    isSettingsScreen = capability in viewModel.settingsCapabilities,
                    onOpenSettings = {
                        if (state.capabilities[capability]?.needsSettingsScreen == true) {
                            context.openAppSettings()
                        } else {
                            context.openSettingsFor(capability)
                        }
                    },
                    onRecheck = viewModel::recheck,
                    // There is nothing to continue to here: this screen is not
                    // a step, so "skip it" would be a button that does nothing.
                    onContinueWithout = {},
                    showContinueWithout = false,
                )
            }

            OutlinedButton(
                onClick = viewModel::recheck,
                enabled = !state.checking,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.permissions_recheck))
            }
        }
    }
}
