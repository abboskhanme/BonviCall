package uz.bonvi.call.data.remote

import com.squareup.moshi.Moshi
import kotlinx.coroutines.runBlocking
import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route
import timber.log.Timber
import uz.bonvi.call.data.remote.api.DeviceAuthApi
import uz.bonvi.call.data.remote.dto.DeviceRefreshIn
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.AuthStateRule
import javax.inject.Inject
import javax.inject.Provider
import javax.inject.Singleton

/**
 * Refreshes an expired access token, once, and replays the request (T79, N25).
 *
 * ═══ The rule ══════════════════════════════════════════════════════════════
 * **A phone whose token expires holds its queue and reports why. It never
 * discards.** The natural implementation of "the token expired" is to clear
 * local state and start again, and what that clears is calls that happened and
 * have not reached the server. N25 exists because that failure is silent: the
 * phone looks healthy, the panel just has fewer calls than the handset made.
 *
 * So when the refresh itself is refused, this class writes
 * `DeviceAuthState.AUTH_EXPIRED` and **leaves every queued row where it is**.
 * The upload worker stops sending, the home screen says why, and the whole
 * backlog uploads the moment the device is re-enrolled.
 *
 * `Authenticator` rather than an interceptor: OkHttp calls it only on a 401,
 * gives it the failed request to rebuild, and — importantly — will not loop.
 * `responseCount` caps it at one attempt per request anyway.
 *
 * `runBlocking` is forbidden outside tests (CONVENTIONS-CLIENT.md §8) and this
 * is the second named exception, for the same reason as `SessionStore`'s
 * snapshot: OkHttp's `Authenticator` contract is synchronous, it is invoked on
 * a background OkHttp thread and never on the main thread, and the alternative
 * is no token refresh at all.
 */
@Singleton
class TokenAuthenticator @Inject constructor(
    private val session: SessionStore,
    private val api: Provider<DeviceAuthApi>,
    private val moshi: Moshi,
) : Authenticator {

    override fun authenticate(route: Route?, response: Response): Request? {
        // One attempt. A second 401 after a fresh token is not a stale token.
        if (responseCount(response) > 1) return null

        val refreshToken = session.snapshot.refreshToken ?: run {
            markExpired(null)
            return null
        }

        if (session.snapshot.installationId == null) return null

        return runBlocking {
            @Suppress("TooGenericExceptionCaught")
            val refreshed = try {
                // The installation is identified by the X-Installation-Id
                // header (CONVENTIONS.md §4.5), not by the body — a token from
                // another installation is a 401 `installation_mismatch` (N24).
                api.get().refresh(DeviceRefreshIn(refreshToken = refreshToken))
            } catch (error: Exception) {
                // No network. NOT auth_expired — the session may be perfectly
                // valid and the phone is simply in a lift. Treating this as
                // expiry is how a queue gets held for a reason that was not
                // true.
                Timber.i("Token refresh could not reach the server; will retry")
                return@runBlocking null
            }

            val body = refreshed.body()
            if (!refreshed.isSuccessful || body == null) {
                val failure = refreshed.toFailure(moshi)
                if (failure.status == UNAUTHORIZED || failure.status == FORBIDDEN) {
                    markExpired(failure.code)
                }
                // 426 here is N34's refusal, and it arrives only once the queue
                // has drained. The state changes what the UI says; the queue is
                // untouched either way.
                if (failure.status == VERSION_UNSUPPORTED) {
                    session.saveAuthState(
                        AuthStateRule.next(
                            session.authStateSnapshot(), failure.status, failure.code,
                        ).wire,
                    )
                }
                return@runBlocking null
            }

            session.saveTokens(
                access = body.accessToken,
                refresh = body.refreshToken,
                verificationMethod = body.verificationMethod?.value,
            )
            response.request.newBuilder()
                .header("Authorization", "Bearer ${body.accessToken}")
                .build()
        }
    }

    private fun markExpired(code: String?) {
        val state = AuthStateRule.onRefreshRefused(code)
        Timber.w("Refresh refused (%s); holding the queue and reporting %s", code, state.wire)
        runBlocking { session.saveAuthState(state.wire) }
    }

    private fun responseCount(response: Response): Int {
        var count = 1
        var prior = response.priorResponse
        while (prior != null) {
            count++
            prior = prior.priorResponse
        }
        return count
    }

    private companion object {
        const val UNAUTHORIZED = 401
        const val FORBIDDEN = 403
        const val VERSION_UNSUPPORTED = 426
    }
}
