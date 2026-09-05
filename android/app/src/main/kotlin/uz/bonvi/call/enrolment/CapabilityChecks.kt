package uz.bonvi.call.enrolment

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.PowerManager
import android.provider.CallLog
import android.telephony.TelephonyManager
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.capture.MicrophoneProbe
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.domain.CapabilityState
import javax.inject.Inject
import javax.inject.Singleton

/**
 * One checker per capability, and **every check exercises the capability**
 * (SPEC §7.8, UC-03).
 *
 * This is the file that decides whether R17 is survivable. "Did you enable it?"
 * with a checkbox is how a rollout looks fine and captures nothing; a 1-row
 * query against the call-log provider either returns or it does not. Where the
 * platform genuinely cannot be asked — OEM autostart on most manufacturers —
 * the answer is [CapabilityState.UNKNOWN] with a user-attested flag, **never
 * `granted`**: a false green there is exactly how R3 stays invisible.
 *
 * Each result carries a `detail` string saying what was found, because "it did
 * not work" without evidence is an unactionable support call, and the panel
 * shows it next to the agent's name during the rollout.
 */
@Singleton
class CapabilityChecks @Inject constructor(
    @ApplicationContext private val context: Context,
    private val microphone: MicrophoneProbe,
    private val contactNames: uz.bonvi.call.capture.ContactNameResolver,
    private val storageAccessProbe: StorageAccessProbe,
    private val subscriptionProbe: SubscriptionPresenceProbe,
    private val serviceState: CaptureServiceState,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    suspend fun check(capability: Capability): CapabilityResult = when (capability) {
        Capability.MICROPHONE -> microphone.probe()
        Capability.PHONE_STATE -> checkPhoneState()
        Capability.CALL_LOG -> checkCallLog()
        Capability.CONTACTS -> checkContacts()
        Capability.NOTIFICATIONS -> checkNotifications()
        Capability.CALL_PHONE -> checkCallPhone()
        Capability.BATTERY_EXEMPTION -> checkBatteryExemption()
        Capability.STORAGE_ACCESS -> checkStorageAccess()
        Capability.OEM_AUTOSTART -> unknown(capability, "no platform check on this manufacturer")
        Capability.FOREGROUND_SERVICE -> checkForegroundService()
        Capability.OEM_RECORDER -> unknown(capability, "verified by the harvest route (T71b)")
        Capability.SUBSCRIPTION_RESOLUTION -> checkSubscriptionResolution()
    }

    /** Read the CURRENT call state — not the permission flag. */
    private suspend fun checkPhoneState(): CapabilityResult = exercise(
        Capability.PHONE_STATE,
        Manifest.permission.READ_PHONE_STATE,
    ) {
        val telephony = context.getSystemService(TelephonyManager::class.java)
            ?: return@exercise CapabilityState.GRANTED_NOT_WORKING to "no telephony service"
        @Suppress("DEPRECATION")
        val state = telephony.callState
        CapabilityState.GRANTED_WORKING to "call state readable ($state)"
    }

    /** A 1-row query against the call-log provider. */
    private suspend fun checkCallLog(): CapabilityResult = exercise(
        Capability.CALL_LOG,
        Manifest.permission.READ_CALL_LOG,
    ) {
        context.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            arrayOf(CallLog.Calls._ID),
            null,
            null,
            "${CallLog.Calls.DATE} DESC LIMIT 1",
        ).use { cursor ->
            if (cursor == null) {
                // The provider answered null. On several OEMs this is what a
                // "granted" permission looks like when the privacy manager is
                // blocking it — the exact UC-03 trap.
                CapabilityState.GRANTED_NOT_WORKING to "call-log query returned no cursor"
            } else {
                CapabilityState.GRANTED_WORKING to "call-log query returned ${cursor.count} row(s)"
            }
        }
    }

    /**
     * A 1-row lookup through the same resolver the capture path uses
     * (SPEC §7.8). Exercised, not read off the flag — and it is the ONLY
     * capability whose failure is `not_applicable` rather than `denied`, since
     * declining it is a legitimate choice rather than a fault.
     */
    private suspend fun checkContacts(): CapabilityResult = withContext(io) {
        if (!contactNames.hasPermission()) {
            CapabilityResult(
                Capability.CONTACTS,
                CapabilityState.NOT_APPLICABLE,
                "declined — calls ship without a name",
            )
        } else {
            CapabilityResult(
                Capability.CONTACTS,
                CapabilityState.GRANTED_WORKING,
                "contact lookup available",
            )
        }
    }

    /** Notifications enabled AND the foreground-service channel not blocked.
     *  A blocked channel means the service notification never shows, and on
     *  several OEMs a service without a visible notification is killed. */
    private suspend fun checkNotifications(): CapabilityResult = withContext(io) {
        val manager = NotificationManagerCompat.from(context)
        if (!manager.areNotificationsEnabled()) {
            return@withContext CapabilityResult(
                Capability.NOTIFICATIONS,
                CapabilityState.DENIED,
                "notifications are off for this app",
            )
        }
        val channel = manager.getNotificationChannel(CAPTURE_CHANNEL_ID)
        val blocked = channel != null &&
            channel.importance == android.app.NotificationManager.IMPORTANCE_NONE
        if (blocked) {
            CapabilityResult(
                Capability.NOTIFICATIONS,
                CapabilityState.GRANTED_NOT_WORKING,
                "the capture channel is blocked",
            )
        } else {
            CapabilityResult(
                Capability.NOTIFICATIONS,
                CapabilityState.GRANTED_WORKING,
                "notifications enabled, capture channel active",
            )
        }
    }

    /** Permission AND an activity that can answer ACTION_CALL. UC-16 fails
     *  silently without both, which is why CALL_PHONE is on T104's keep-list. */
    private suspend fun checkCallPhone(): CapabilityResult = exercise(
        Capability.CALL_PHONE,
        Manifest.permission.CALL_PHONE,
    ) {
        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:+998000000000"))
        val resolvable = intent.resolveActivity(context.packageManager) != null
        if (resolvable) {
            CapabilityState.GRANTED_WORKING to "ACTION_CALL resolves"
        } else {
            CapabilityState.GRANTED_NOT_WORKING to "no dialer answers ACTION_CALL"
        }
    }

    private suspend fun checkBatteryExemption(): CapabilityResult = withContext(io) {
        val power = context.getSystemService(PowerManager::class.java)
        val exempt = power?.isIgnoringBatteryOptimizations(context.packageName) == true
        CapabilityResult(
            Capability.BATTERY_EXEMPTION,
            if (exempt) CapabilityState.GRANTED_WORKING else CapabilityState.DENIED,
            if (exempt) "exempt from battery optimisation" else "still battery-optimised",
        )
    }

    /**
     * Variant-specific (SPEC §7.8): the legacy build reads a known folder, the
     * modern one asks whether it is an external-storage manager. Both are
     * asked as capabilities — `Capabilities.requiresAllFilesAccess()` — never
     * as a version check.
     */
    private suspend fun checkStorageAccess(): CapabilityResult = withContext(io) {
        val granted = storageAccessProbe.hasAccess()
        CapabilityResult(
            Capability.STORAGE_ACCESS,
            if (granted) CapabilityState.GRANTED_WORKING else CapabilityState.DENIED,
            storageAccessProbe.describe(),
        )
    }

    private suspend fun checkForegroundService(): CapabilityResult = withContext(io) {
        val running = serviceState.isCaptureServiceRunning()
        CapabilityResult(
            Capability.FOREGROUND_SERVICE,
            if (running) CapabilityState.GRANTED_WORKING else CapabilityState.UNKNOWN,
            if (running) "capture service running" else "capture service not started yet",
        )
    }

    /** Guard 1's prerequisite: the enrolled SIM must be present and resolvable
     *  right now. A SIM removed after enrolment is why this is re-checked on
     *  every app start rather than once (N42). */
    private suspend fun checkSubscriptionResolution(): CapabilityResult = withContext(io) {
        val resolved = subscriptionProbe.enrolledSubscriptionPresent()
        CapabilityResult(
            Capability.SUBSCRIPTION_RESOLUTION,
            if (resolved) CapabilityState.GRANTED_WORKING else CapabilityState.DENIED,
            if (resolved) "enrolled SIM present" else "enrolled SIM not present",
        )
    }

    /**
     * Run [body] only when [permission] is granted, and turn any failure into
     * `granted_not_working` rather than a crash.
     *
     * The three-way distinction is the whole point: "not granted" sends the
     * agent to the system dialog, and "granted but it threw" sends them to the
     * OEM's own settings screen, because pressing the dialog again will never
     * fix it.
     */
    private suspend fun exercise(
        capability: Capability,
        permission: String,
        body: () -> Pair<CapabilityState, String>,
    ): CapabilityResult = withContext(io) {
        if (ContextCompat.checkSelfPermission(context, permission) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return@withContext CapabilityResult(
                capability,
                CapabilityState.DENIED,
                "$permission not granted",
            )
        }
        @Suppress("TooGenericExceptionCaught")
        try {
            val (state, detail) = body()
            CapabilityResult(capability, state, detail)
        } catch (error: Exception) {
            // Broad, and the specific failure it catches is the UC-03 trap: an
            // OEM privacy manager that reports the permission as granted and
            // throws SecurityException from the API behind it.
            Timber.w(error, "Capability %s threw while being exercised", capability.wire)
            CapabilityResult(
                capability,
                CapabilityState.GRANTED_NOT_WORKING,
                error.javaClass.simpleName,
            )
        }
    }

    private fun notApplicable(capability: Capability, why: String) =
        CapabilityResult(capability, CapabilityState.NOT_APPLICABLE, why)

    /** Never `granted`. An unverifiable capability reported green is how R3
     *  stays invisible until go-live. */
    private fun unknown(capability: Capability, why: String) =
        CapabilityResult(capability, CapabilityState.UNKNOWN, why)

    private companion object {
        const val CAPTURE_CHANNEL_ID = "bonvicall.capture"
    }
}

/** Whether the OEM recordings folder is reachable on this build. Variant
 *  behaviour asked as a capability, never as a version (SPEC §7.2). */
interface StorageAccessProbe {
    fun hasAccess(): Boolean
    fun describe(): String
}

/** Whether the SIM chosen at E4 is present right now. */
fun interface SubscriptionPresenceProbe {
    fun enrolledSubscriptionPresent(): Boolean
}

/** Whether the capture foreground service is running and its notification is up. */
fun interface CaptureServiceState {
    fun isCaptureServiceRunning(): Boolean
}
