package uz.bonvi.call.ui.calls

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.MyCall
import uz.bonvi.call.domain.MyCallsGateway
import javax.inject.Inject

/**
 * The employee's own calls, read from the server (client request, N41).
 *
 * Three things this screen has to get right, and they are all here rather than
 * in the composable so they can be tested:
 *
 * 1. **It shows what the server holds**, never the local queue. A local list
 *    would show calls that never uploaded and hide calls the recovery sweep
 *    found — two errors pointing opposite ways.
 * 2. **Own calls only, enforced server-side.** There is no filter in this file
 *    and there must never be one: a client-side narrowing over a wider
 *    response is not a boundary, it is a decoration on one.
 * 3. **Audio only where audio exists**, with the honest reason where it does
 *    not. Never a dead play button.
 */
@HiltViewModel
class MyCallsViewModel @Inject constructor(
    private val gateway: MyCallsGateway,
    private val session: SessionStore,
) : ViewModel() {

    data class UiState(
        val loading: Boolean = true,
        val calls: List<MyCall> = emptyList(),
        val registeredNumber: String? = null,
        val nextCursor: String? = null,
        val hasMore: Boolean = false,
        val message: Message? = null,
    ) {
        val isEmpty: Boolean get() = !loading && calls.isEmpty() && message == null
    }

    /** Each of these says something different and TRUE. "Not deployed yet" is
     *  not "something went wrong", and conflating them makes the honest
     *  messages elsewhere less believable. */
    enum class Message { NOT_AVAILABLE, OFFLINE, FAILED }

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            _state.value = _state.value.copy(
                registeredNumber = session.registeredNumberDisplay.first(),
            )
            load(reset = true)
        }
    }

    fun refresh() {
        viewModelScope.launch { load(reset = true) }
    }

    fun loadMore() {
        if (!_state.value.hasMore) return
        viewModelScope.launch { load(reset = false) }
    }

    private suspend fun load(reset: Boolean) {
        _state.value = _state.value.copy(loading = true, message = null)
        val cursor = if (reset) null else _state.value.nextCursor

        when (val result = gateway.page(cursor)) {
            is MyCallsGateway.Result.Page -> {
                val existing = if (reset) emptyList() else _state.value.calls
                _state.value = _state.value.copy(
                    loading = false,
                    calls = existing + result.page.items,
                    nextCursor = result.page.nextCursor,
                    hasMore = result.page.hasMore,
                )
            }

            is MyCallsGateway.Result.NotAvailable ->
                _state.value = _state.value.copy(loading = false, message = Message.NOT_AVAILABLE)

            is MyCallsGateway.Result.Offline ->
                _state.value = _state.value.copy(loading = false, message = Message.OFFLINE)

            is MyCallsGateway.Result.Failed ->
                _state.value = _state.value.copy(loading = false, message = Message.FAILED)
        }
    }

    /** The stream URL, or null when the server holds no audio for this call. */
    suspend fun audioUrl(call: MyCall): String? =
        if (call.playable) gateway.audioUrl(call.id) else null
}
