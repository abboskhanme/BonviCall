package uz.bonvi.call.ui.permissions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.domain.runtimePermission
import uz.bonvi.call.service.CapabilityRefresh
import javax.inject.Inject

/**
 * "Ruxsatlar" — the same nine checks E2 runs, reachable for ever.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Enrolment lets an agent continue without a permission on purpose (UC-14): a
 * phone that logs calls without audio is a supported state, and refusing to
 * enrol it is strictly worse. What was missing is the way BACK. Once E2 was
 * behind them, the only route to a skipped permission was to be told, by an
 * admin reading the panel, which system settings screen to open — and the app
 * itself, which knows exactly which check fails and why, said nothing.
 *
 * So this screen is the same rows with no flow attached: what works, what does
 * not, why it matters, and the button that opens the right settings page.
 *
 * Every visit reports to the server, so the panel stops describing the day of
 * installation the moment somebody looks at this screen.
 * ═══════════════════════════════════════════════════════════════════════════
 */
@HiltViewModel
class PermissionsViewModel @Inject constructor(
    private val refresh: CapabilityRefresh,
) : ViewModel() {

    data class UiState(
        val checking: Boolean = false,
        val capabilities: Map<Capability, CapabilityResult> = emptyMap(),
    ) {
        /** Required capabilities that are not working — the count the screen
         *  leads with, because it is the answer to "am I set up". */
        val blocking: List<Capability>
            get() = CaptureReadiness.E2_ORDER.filter { capability ->
                capability !in CaptureReadiness.OPTIONAL &&
                    capabilities[capability]?.isWorking != true
            }

        val checked: Boolean get() = capabilities.isNotEmpty()
    }

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    /** The order E2 asks in, so the two screens read the same way. */
    val order: List<Capability> = CaptureReadiness.E2_ORDER

    /** The six that are an ordinary dialog, asked for in one request. */
    val runtimePermissions: List<String> =
        order.mapNotNull { it.runtimePermission() }.distinct()

    /** The three that are a settings screen rather than a dialog. */
    val settingsCapabilities: List<Capability> = order.filter { it.runtimePermission() == null }

    init {
        recheck()
    }

    /**
     * Run everything and report it.
     *
     * Called on entry and again on every resume — which is the moment that
     * matters, because the way a person grants "all files access" is to leave
     * this screen for the system settings and come back.
     */
    fun recheck() {
        if (_state.value.checking) return
        viewModelScope.launch {
            _state.value = _state.value.copy(checking = true)
            val report = refresh.full()
            _state.value = UiState(
                checking = false,
                capabilities = report.results.associateBy { it.capability },
            )
        }
    }
}
