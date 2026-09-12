package uz.bonvi.call.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.DeviceAuthState
import uz.bonvi.call.service.CaptureService
import javax.inject.Inject

/**
 * The employee's own view of what their phone is doing (N41, T76).
 *
 * ═══ The one rule ══════════════════════════════════════════════════════════
 * **It says "qayd etilmoqda" only when that is true**, and when it is not it
 * names the reason. The state where an app claims to be capturing and is not is
 * the single most expensive failure in this product: the rollout looks
 * finished, nobody goes looking, and the calls are simply absent. That is the
 * same rule E6 keys off — one truth, two screens.
 *
 * The number is at the top, permanently, because a person carrying a recorded
 * phone should never have to open a menu to find out which number it is.
 */
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val session: SessionStore,
    private val queue: CallQueueRepository,
) : ViewModel() {

    data class UiState(
        val registeredNumber: String? = null,
        val agentName: String? = null,

        /** The installation is bound AND the number was proven — the real token
         *  pair is issued only then, so its presence is the proof. */
        val enrolled: Boolean = false,
        val authState: DeviceAuthState = DeviceAuthState.ACTIVE,
        val serviceRunning: Boolean = false,

        val pending: Int = 0,
        val parked: Int = 0,
    ) {
        /** Capture is only claimed when every part of it is true. */
        val capturing: Boolean get() = enrolled && authState.canCapture && serviceRunning

        // `blockedByAuth` was here and nothing read it: `HomeScreen` branches
        // on the [authState] itself, because the three reasons capture can be
        // stopped by auth — revoked, expired, under-version — each need their
        // own sentence, and one boolean cannot carry three.

        /** Queued calls are never lost, whatever the state (N25). Worth saying
         *  out loud on the screen where somebody is worrying about it. */
        val hasBacklog: Boolean get() = pending > 0 || parked > 0
    }

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        refresh()
    }

    /** Re-read on every entry: the service can be killed by the OS between two
     *  visits to this screen, and a stale "ishlayapti" is the lie this screen
     *  exists to avoid. */
    fun refresh() {
        viewModelScope.launch {
            val depth = queue.depth()
            _state.value = UiState(
                registeredNumber = session.registeredNumberDisplay.first(),
                agentName = session.agentName.first(),
                enrolled = session.snapshot.installationId != null &&
                    session.snapshot.refreshToken != null,
                authState = session.authStateSnapshot(),
                serviceRunning = CaptureService.isRunning,
                pending = depth.pending,
                parked = depth.parked,
            )
        }
    }
}
