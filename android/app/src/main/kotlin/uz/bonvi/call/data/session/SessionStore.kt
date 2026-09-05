package uz.bonvi.call.data.session

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.domain.ServerAddress
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

private val Context.sessionDataStore by preferencesDataStore(name = "bonvicall_session")

/**
 * The installation's identity, and the number it records.
 *
 * ═══ N41 lives here ════════════════════════════════════════════════════════
 * [registeredNumberDisplay] is written the moment the code is redeemed (E1) and
 * is shown on EVERY screen from then on — the enrolment steps, the home screen,
 * the foreground-service notification. It is not a settings detail; it is the
 * sentence that makes the privacy boundary visible to the person carrying the
 * phone, and it is true before the install finishes rather than after.
 *
 * Nothing here is backed up (`android:allowBackup="false"`): an
 * installation-bound credential restored onto a different handset is exactly
 * the `installation_mismatch` the server refuses (N24).
 */
@Singleton
class SessionStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val store = context.sessionDataStore

    val installationId: Flow<String?> = store.data.map { it[KEY_INSTALLATION_ID] }
    val accessToken: Flow<String?> = store.data.map { it[KEY_ACCESS_TOKEN] }
    val refreshToken: Flow<String?> = store.data.map { it[KEY_REFRESH_TOKEN] }

    /** The number the app records, formatted for a human. N41's sentence. */
    val registeredNumberDisplay: Flow<String?> = store.data.map { it[KEY_NUMBER_DISPLAY] }
    val registeredNumberE164: Flow<String?> = store.data.map { it[KEY_NUMBER_E164] }
    val agentName: Flow<String?> = store.data.map { it[KEY_AGENT_NAME] }

    /** Chosen at E4 and enforced by Guard 1 from then on. */
    val simSubscriptionId: Flow<Int?> = store.data.map { it[KEY_SUBSCRIPTION_ID] }

    /** How the number was proven. `admin_attested` is deliberately weaker than
     *  the other two and is rendered differently everywhere (SPEC §9.3), so the
     *  identity anchor cannot silently degrade. */
    val verificationMethod: Flow<String?> = store.data.map { it[KEY_VERIFICATION_METHOD] }

    val baseUrl: Flow<String> = store.data.map { it[KEY_BASE_URL] ?: DEFAULT_BASE_URL }

    suspend fun saveEnrolment(
        installationId: String,
        agentName: String,
        numberDisplay: String,
        numberE164: String,
    ) = edit {
        it[KEY_INSTALLATION_ID] = installationId
        it[KEY_AGENT_NAME] = agentName
        it[KEY_NUMBER_DISPLAY] = numberDisplay
        it[KEY_NUMBER_E164] = numberE164
    }

    suspend fun saveTokens(access: String, refresh: String, verificationMethod: String?) = edit {
        it[KEY_ACCESS_TOKEN] = access
        it[KEY_REFRESH_TOKEN] = refresh
        verificationMethod?.let { method -> it[KEY_VERIFICATION_METHOD] = method }
    }

    suspend fun saveProvisionalToken(token: String) = edit { it[KEY_ACCESS_TOKEN] = token }

    suspend fun saveSubscription(subscriptionId: Int) = edit {
        it[KEY_SUBSCRIPTION_ID] = subscriptionId
    }

    /**
     * Point this installation at a server.
     *
     * ⚠️ **Refused in a release build.** The guard is here rather than only in
     * the screen that offers it: hiding a control is not access control — the
     * same mistake as a nav menu without a route gate — and what a repointed
     * handset would send elsewhere is every call the employee makes.
     *
     * @return true when the address was written.
     */
    suspend fun saveBaseUrl(url: String, source: ServerAddress.Source): Boolean {
        if (source == ServerAddress.Source.MANUAL && !BuildConfig.DEBUG) {
            Timber.w("Refusing a manual server address in a release build")
            return false
        }
        return when (val validation = ServerAddress.validate(url)) {
            is ServerAddress.Validation.Invalid -> {
                Timber.w("Refusing an invalid server address: %s", validation.reason)
                false
            }

            is ServerAddress.Validation.Valid -> {
                edit { it[KEY_BASE_URL] = validation.normalised }
                true
            }
        }
    }

    /** Whether the address may be typed in on this build. Debug only. */
    val serverAddressEditable: Boolean get() = BuildConfig.DEBUG

    /**
     * Why the device can or cannot send (T79/N25, T83/N34).
     *
     * Writing this NEVER touches the queue. There is no state in which the
     * client throws captured calls away — that is the whole point of N25, and
     * the reason the state and the queue live in different stores.
     */
    suspend fun saveAuthState(state: String) = edit { it[KEY_AUTH_STATE] = state }

    fun authStateSnapshot(): uz.bonvi.call.domain.DeviceAuthState =
        uz.bonvi.call.domain.DeviceAuthState.entries
            .firstOrNull { it.wire == snapshot.authState }
            ?: uz.bonvi.call.domain.DeviceAuthState.ACTIVE

    val authState: Flow<uz.bonvi.call.domain.DeviceAuthState> = store.data.map { prefs ->
        uz.bonvi.call.domain.DeviceAuthState.entries
            .firstOrNull { it.wire == prefs[KEY_AUTH_STATE] }
            ?: uz.bonvi.call.domain.DeviceAuthState.ACTIVE
    }

    /** UC-08. Revocation leaves nothing behind that could re-bind. */
    suspend fun clear() = edit { it.clear() }

    private suspend fun edit(block: (androidx.datastore.preferences.core.MutablePreferences) -> Unit) {
        store.edit(block)
    }

    /**
     * A synchronous mirror of the three values OkHttp needs.
     *
     * OkHttp's interceptor chain cannot suspend, and `runBlocking` is forbidden
     * outside tests (CONVENTIONS-CLIENT.md §8) — blocking an OkHttp thread on a
     * disk read is how a slow filesystem turns into a request timeout. So the
     * DataStore flow is collected once into a volatile snapshot and the
     * interceptors read that. It is eventually consistent by a few
     * milliseconds, which is exactly as consistent as the request that follows
     * a write needs it to be.
     */
    @Volatile
    var snapshot: Snapshot = Snapshot()
        private set

    data class Snapshot(
        val installationId: String? = null,
        val accessToken: String? = null,
        val baseUrl: String = DEFAULT_BASE_URL,
        val simSubscriptionId: Int? = null,
        val registeredNumberDisplay: String? = null,
        val registeredNumberE164: String? = null,
        val refreshToken: String? = null,
        /** [uz.bonvi.call.domain.DeviceAuthState]'s wire value. Read
         *  synchronously by the OkHttp authenticator and by the heartbeat. */
        val authState: String = "active",
    )

    init {
        // Application-scoped by construction: SessionStore is a @Singleton that
        // lives as long as the process. Not GlobalScope — this scope is owned
        // by an object with a defined lifetime.
        CoroutineScope(SupervisorJob()).launch {
            store.data
                .onEach { prefs ->
                    snapshot = Snapshot(
                        installationId = prefs[KEY_INSTALLATION_ID],
                        accessToken = prefs[KEY_ACCESS_TOKEN],
                        baseUrl = prefs[KEY_BASE_URL] ?: DEFAULT_BASE_URL,
                        simSubscriptionId = prefs[KEY_SUBSCRIPTION_ID],
                        registeredNumberDisplay = prefs[KEY_NUMBER_DISPLAY],
                        registeredNumberE164 = prefs[KEY_NUMBER_E164],
                        refreshToken = prefs[KEY_REFRESH_TOKEN],
                        authState = prefs[KEY_AUTH_STATE] ?: "active",
                    )
                }
                .collect()
        }
    }

    companion object {
        /** Overridden at enrolment: the deep link carries the server it
         *  belongs to. The build supplies the fallback — production for a
         *  release, the configured `bonvicall.devHost` for a debug build —
         *  because a code typed by hand rather than opened from a link leaves
         *  this value in charge, and a wrong one reports itself to the user as
         *  "no internet" on a phone with perfectly good wifi. */
        val DEFAULT_BASE_URL: String = uz.bonvi.call.BuildConfig.DEFAULT_BASE_URL

        private val KEY_INSTALLATION_ID = stringPreferencesKey("installation_id")
        private val KEY_ACCESS_TOKEN = stringPreferencesKey("access_token")
        private val KEY_REFRESH_TOKEN = stringPreferencesKey("refresh_token")
        private val KEY_NUMBER_DISPLAY = stringPreferencesKey("number_display")
        private val KEY_NUMBER_E164 = stringPreferencesKey("number_e164")
        private val KEY_AGENT_NAME = stringPreferencesKey("agent_name")
        private val KEY_VERIFICATION_METHOD = stringPreferencesKey("verification_method")
        private val KEY_BASE_URL = stringPreferencesKey("base_url")
        private val KEY_SUBSCRIPTION_ID = intPreferencesKey("sim_subscription_id")
        private val KEY_AUTH_STATE = stringPreferencesKey("auth_state")
    }
}
