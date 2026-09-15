package uz.bonvi.call.data.session

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.first
import uz.bonvi.call.domain.CapabilityDelta
import javax.inject.Inject
import javax.inject.Singleton

private val Context.capabilityDataStore by preferencesDataStore(name = "bonvicall_capabilities")

/**
 * What this phone last told the server about its own capabilities.
 *
 * It exists so [uz.bonvi.call.service.CapabilityRefresh] can run on every
 * heartbeat and every app open and still send **nothing** while the answers
 * are unchanged — a phone whose permissions have not moved must not spend
 * data, battery or a row in the panel's history saying so.
 *
 * Its own DataStore rather than a key inside [SessionStore]: this survives a
 * token refresh, a re-verification and a server address change, and none of
 * those should clear it. It is cleared where it should be — by the OS, when
 * the app's data is wiped, which is also when the enrolment goes.
 *
 * The format is [CapabilityDelta]'s, kept there with the comparison it serves:
 * what "changed" means and how it is written down are one decision.
 */
@Singleton
class CapabilitySnapshotStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    private val store = context.capabilityDataStore

    /** The last reported fingerprint per capability. Empty when nothing has been sent. */
    suspend fun last(): Map<String, String> =
        CapabilityDelta.decode(store.data.first()[KEY_SNAPSHOT].orEmpty())

    suspend fun remember(snapshot: Map<String, String>) {
        store.edit { preferences -> preferences[KEY_SNAPSHOT] = CapabilityDelta.encode(snapshot) }
    }

    private companion object {
        val KEY_SNAPSHOT = stringPreferencesKey("capability_snapshot")
    }
}
