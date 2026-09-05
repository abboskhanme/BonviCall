package uz.bonvi.call.data.repository

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.data.remote.api.ServerReachabilityApi
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.ServerAddress
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Check a server address, then commit it.
 *
 * The order is the feature: **test before saving**. Saving an unreachable
 * address leaves the phone pointed at nothing, and the next failure is
 * indistinguishable from being offline — which is exactly the confusion that
 * cost an afternoon on real hardware.
 */
@Singleton
class ServerAddressRepository @Inject constructor(
    private val reachability: ServerReachabilityApi,
    private val session: SessionStore,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    sealed interface CheckResult {
        /** A BonviCall server answered `/healthz`. */
        data object Reachable : CheckResult

        /** The address is not an address. Shown before anything is sent. */
        data class Invalid(val reason: ServerAddress.Validation.Reason) : CheckResult

        /** Nothing answered — wrong host, tunnel down, or no network. */
        data object Unreachable : CheckResult

        /** Something answered and it was not a BonviCall server. */
        data class NotBonviCall(val status: Int) : CheckResult
    }

    /**
     * The last transport failure, by exception class.
     *
     * `CleartextNotPermittedException` and `ConnectException` send somebody to
     * two different places; "connection failed" sends them nowhere. Kept
     * separately from [CheckResult] so the verdict stays a small closed set and
     * the detail stays honest.
     */
    @Volatile
    private var lastFailure: String? = null

    fun lastFailureDetail(): String? = lastFailure

    suspend fun check(raw: String): CheckResult = withContext(io) {
        val validation = ServerAddress.validate(raw)
        if (validation is ServerAddress.Validation.Invalid) {
            return@withContext CheckResult.Invalid(validation.reason)
        }
        val normalised = (validation as ServerAddress.Validation.Valid).normalised

        @Suppress("TooGenericExceptionCaught")
        val response = try {
            reachability.healthz("$normalised/healthz")
        } catch (error: Exception) {
            // Broad, and the specific failures are UnknownHostException (a
            // tunnel that moved), ConnectException (nothing listening) and
            // SSLException. All three mean the same thing to the person
            // reading the screen: nothing answered at this address.
            lastFailure = "${error.javaClass.simpleName}: ${error.message}"
            Timber.i("Server check failed for %s: %s", normalised, lastFailure)
            return@withContext CheckResult.Unreachable
        }

        lastFailure = null
        if (response.isSuccessful) {
            CheckResult.Reachable
        } else {
            // A proxy error page, a tunnel's own 502, or somebody else's
            // server. Distinguished from Unreachable because the fix differs:
            // one is a wrong address, the other is a dead one.
            CheckResult.NotBonviCall(response.code())
        }
    }

    /** Commit it. Refused in a release build by [SessionStore.saveBaseUrl]. */
    suspend fun save(raw: String): Boolean =
        session.saveBaseUrl(raw, ServerAddress.Source.MANUAL)

    /** From the enrolment deep link, which wins over anything typed. */
    suspend fun saveFromDeepLink(raw: String): Boolean =
        session.saveBaseUrl(raw, ServerAddress.Source.DEEP_LINK)

    val editable: Boolean get() = session.serverAddressEditable
}
