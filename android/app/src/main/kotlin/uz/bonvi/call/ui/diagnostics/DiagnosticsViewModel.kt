package uz.bonvi.call.ui.diagnostics

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.repository.ServerAddressRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.service.CaptureService
import javax.inject.Inject

/**
 * "Ilova holati" — what the phone is doing, and why not (UC-07, N41).
 *
 * This is the screen an admin asks an agent to read out during an assisted
 * install, and the one `docs/QOLLANMA.md` now points at. It answers three
 * questions in the order a person asks them: is it working, what is waiting,
 * and — in a debug build — which server is it talking to.
 */
@HiltViewModel
class DiagnosticsViewModel @Inject constructor(
    private val session: SessionStore,
    private val queue: CallQueueRepository,
    private val serverAddress: ServerAddressRepository,
) : ViewModel() {

    data class UiState(
        val registeredNumber: String? = null,
        val capturing: Boolean = false,
        val serviceRunning: Boolean = false,
        val pending: Int = 0,
        val parked: Int = 0,
        /** Name AND code: the version gate reads the code, so a phone being
         *  diagnosed has to be able to say it. */
        val appVersion: String = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
        val variant: String = BuildConfig.APP_VARIANT,

        /** Debug builds only. A release build never renders this section. */
        val serverEditable: Boolean = false,
        val serverAddress: String = "",
        val serverCheck: ServerAddressRepository.CheckResult? = null,
        /**
         * The failure in the words the network gave us.
         *
         * Adopted from the parallel diagnostics work, and it is the better
         * idea: `CleartextNotPermittedException` and `ConnectException` send
         * somebody to two different places, and "connection failed" sends them
         * nowhere.
         */
        val serverCheckDetail: String? = null,
        val serverSaved: Boolean = false,
        val checking: Boolean = false,
    )

    private val _state = MutableStateFlow(UiState(serverEditable = serverAddress.editable))
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            val depth = queue.depth()
            _state.value = _state.value.copy(
                registeredNumber = session.registeredNumberDisplay.first(),
                capturing = session.authStateSnapshot().canCapture &&
                    session.snapshot.installationId != null,
                serviceRunning = CaptureService.isRunning,
                pending = depth.pending,
                parked = depth.parked,
                serverAddress = session.baseUrl.first(),
                serverEditable = serverAddress.editable,
            )
        }
    }

    fun onServerAddressChanged(value: String) {
        // Clear the previous verdict: a result that refers to a different
        // address is worse than no result.
        _state.value = _state.value.copy(
            serverAddress = value,
            serverCheck = null,
            serverSaved = false,
        )
    }

    /**
     * Test the address **before** committing it.
     *
     * Saving an unreachable address leaves the phone pointed at nothing, and
     * the next failure is indistinguishable from being offline — the exact
     * confusion that cost an afternoon on real hardware.
     */
    fun onCheckServer() {
        viewModelScope.launch {
            _state.value = _state.value.copy(checking = true, serverCheck = null)
            val result = serverAddress.check(_state.value.serverAddress)
            _state.value = _state.value.copy(
                checking = false,
                serverCheck = result,
                serverCheckDetail = (result as? ServerAddressRepository.CheckResult.Unreachable)
                    ?.let { serverAddress.lastFailureDetail() },
            )
        }
    }

    fun onSaveServer() {
        viewModelScope.launch {
            val saved = serverAddress.save(_state.value.serverAddress)
            _state.value = _state.value.copy(serverSaved = saved)
            if (saved) refresh()
        }
    }

    /** Only offered once the address has actually answered. */
    fun canSave(): Boolean =
        _state.value.serverCheck is ServerAddressRepository.CheckResult.Reachable
}
