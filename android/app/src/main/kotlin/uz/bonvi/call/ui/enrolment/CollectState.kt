package uz.bonvi.call.ui.enrolment

import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.flow.StateFlow

/**
 * `collectAsStateWithLifecycle`, named once.
 *
 * Lifecycle-aware rather than `collectAsState`: an enrolment screen left in the
 * background while the agent is in the system settings must not keep collecting
 * — on the permissions step that would poll a capability check every time the
 * OS redraws behind the dialog.
 */
@Composable
fun <T> StateFlow<T>.collectAsStateWithLifecycleCompat(): State<T> = collectAsStateWithLifecycle()
