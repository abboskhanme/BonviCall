package uz.bonvi.call.diagnostics

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import javax.inject.Inject

/**
 * What the phone believes about itself, and whether it can reach the server.
 *
 * This screen exists because of a real failure on the first handset the app was
 * ever installed on: the app reported "no internet" while the phone's browser
 * could load the server perfectly well. The cause was a base URL the user could
 * not see and had no way to check. A device that cannot tell you which server
 * it is talking to turns a one-line configuration mistake into an afternoon.
 *
 * So the server address is shown plainly, and the reachability test is a real
 * request rather than a guess from connectivity state — "the phone has wifi"
 * and "the phone can reach our server" are different facts, and it is the
 * second one that decides whether anything works.
 */
@HiltViewModel
class DiagnosticsViewModel @Inject constructor(
    private val session: SessionStore,
    private val client: OkHttpClient,
    @IoDispatcher private val io: CoroutineDispatcher,
) : ViewModel() {

    enum class Reach { UNKNOWN, CHECKING, OK, FAILED }

    data class UiState(
        val baseUrl: String = "",
        val appVersion: String = "",
        val variant: String = "",
        val enrolled: Boolean = false,
        val registeredNumber: String? = null,
        val reach: Reach = Reach.UNKNOWN,
        /** The failure in the words the network gave us, not a paraphrase. */
        val reachDetail: String? = null,
    )

    private val _state = MutableStateFlow(read())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private fun read(): UiState {
        val snapshot = session.snapshot
        return UiState(
            baseUrl = snapshot.baseUrl,
            appVersion = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
            variant = BuildConfig.APP_VARIANT,
            enrolled = snapshot.installationId != null,
            registeredNumber = snapshot.registeredNumberDisplay,
        )
    }

    fun refresh() = _state.update { read().copy(reach = it.reach, reachDetail = it.reachDetail) }

    /**
     * Ask the server whether it is there, over the same client every other
     * request uses — so a cleartext policy or a certificate problem fails here
     * exactly as it would fail during enrolment, rather than being masked by a
     * more permissive check written specially for this screen.
     */
    fun testConnection() {
        _state.update { it.copy(reach = Reach.CHECKING, reachDetail = null) }
        viewModelScope.launch {
            val url = session.snapshot.baseUrl.trimEnd('/') + "/healthz"
            val result = withContext(io) {
                runCatching {
                    client.newCall(Request.Builder().url(url).build()).execute().use { response ->
                        response.code
                    }
                }
            }
            _state.update {
                result.fold(
                    onSuccess = { code ->
                        if (code in 200..299) {
                            it.copy(reach = Reach.OK, reachDetail = null)
                        } else {
                            it.copy(reach = Reach.FAILED, reachDetail = "HTTP $code")
                        }
                    },
                    onFailure = { error ->
                        it.copy(
                            reach = Reach.FAILED,
                            // The exception class matters here: a
                            // CleartextNotPermittedException and a
                            // ConnectException send somebody to two different
                            // places, and "connection failed" sends them
                            // nowhere.
                            reachDetail = "${error.javaClass.simpleName}: ${error.message}",
                        )
                    },
                )
            }
        }
    }
}
