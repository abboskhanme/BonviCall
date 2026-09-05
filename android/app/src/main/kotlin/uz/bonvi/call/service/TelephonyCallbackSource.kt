package uz.bonvi.call.service

import android.content.Context
import android.telephony.TelephonyManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import java.util.concurrent.Executor
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The live call-state source, registered by the foreground service (T69).
 *
 * Two implementations of one idea, chosen by capability rather than by a
 * version check at the call site:
 *
 *  • API 31+ — `TelephonyCallback`, which is the only non-deprecated route and
 *    is registered per subscription, so the subscription is known without
 *    inference;
 *  • below that — `PhoneStateListener`, deprecated but the only option.
 *
 * Both produce the same [CallDetector.Edge] values, so the rules live in one
 * place and neither path can drift from the other.
 *
 * This is the LIVE source. `PhoneStateReceiver` covers the cold case where the
 * process is not running, and both are needed: a phone that has not been opened
 * since a reboot still takes calls.
 */
@Singleton
class TelephonyCallbackSource @Inject constructor(
    @ApplicationContext private val context: Context,
    private val detector: CallDetector,
) {

    private var registered: Any? = null

    fun register(scope: CoroutineScope) {
        if (registered != null) return
        val telephony = context.getSystemService(TelephonyManager::class.java) ?: return

        @Suppress("TooGenericExceptionCaught")
        try {
            registered = if (Capabilities.supportsTelephonyCallback()) {
                registerModern(telephony, scope)
            } else {
                registerLegacy(telephony, scope)
            }
        } catch (error: Exception) {
            // Broad, and the specific failure is a SecurityException from an
            // OEM privacy manager that granted READ_PHONE_STATE and refuses the
            // registration. The manifest receiver still delivers edges, so
            // capture degrades rather than stopping — and the capability check
            // reports `granted_not_working` so the panel says why.
            Timber.w(error, "Could not register the live call-state source")
        }
    }

    /** `@RequiresApi`, and the caller is guarded by
     *  `Capabilities.supportsTelephonyCallback()`, which is
     *  `@ChecksSdkIntAtLeast` — so lint is satisfied without a raw `SDK_INT`
     *  appearing outside core/Capabilities.kt. */
    @androidx.annotation.RequiresApi(android.os.Build.VERSION_CODES.S)
    private fun registerModern(telephony: TelephonyManager, scope: CoroutineScope): Any {
        val executor = Executor { it.run() }
        val callback = ModernCallStateCallback(detector, scope)
        telephony.registerTelephonyCallback(executor, callback)
        return callback
    }

    @Suppress("DEPRECATION")
    private fun registerLegacy(telephony: TelephonyManager, scope: CoroutineScope): Any {
        val listener = LegacyCallStateListener(detector, scope)
        telephony.listen(listener, android.telephony.PhoneStateListener.LISTEN_CALL_STATE)
        return listener
    }

    fun unregister() {
        val current = registered ?: return
        val telephony = context.getSystemService(TelephonyManager::class.java)
        @Suppress("TooGenericExceptionCaught")
        try {
            when {
                Capabilities.supportsTelephonyCallback() &&
                    current is android.telephony.TelephonyCallback ->
                    telephony?.unregisterTelephonyCallback(current)

                current is android.telephony.PhoneStateListener ->
                    @Suppress("DEPRECATION")
                    telephony?.listen(current, android.telephony.PhoneStateListener.LISTEN_NONE)

                else -> Unit
            }
        } catch (error: Exception) {
            // Unregistering a listener the OS has already dropped throws on some
            // OEMs. It cannot be allowed to fail service shutdown.
            Timber.w(error, "Could not unregister the call-state source")
        }
        registered = null
    }
}

/** API 31+. Not deprecated, and registered per subscription. */
@androidx.annotation.RequiresApi(android.os.Build.VERSION_CODES.S)
private class ModernCallStateCallback(
    private val detector: CallDetector,
    private val scope: CoroutineScope,
) : android.telephony.TelephonyCallback(),
    android.telephony.TelephonyCallback.CallStateListener {

    override fun onCallStateChanged(state: Int) {
        detector.onEdge(state.toEdge(LIVE_CALL_ID), scope)
    }
}

/** Below API 31. Deprecated and unavoidable. */
@Suppress("DEPRECATION")
private class LegacyCallStateListener(
    private val detector: CallDetector,
    private val scope: CoroutineScope,
) : android.telephony.PhoneStateListener() {

    override fun onCallStateChanged(state: Int, phoneNumber: String?) {
        detector.onEdge(state.toEdge(LIVE_CALL_ID, phoneNumber), scope)
    }
}

/** The live source carries no call id; the manifest receiver's key is reused so
 *  the two sources address the same in-flight call rather than two. */
private const val LIVE_CALL_ID = "live"

private fun Int.toEdge(callId: String, number: String? = null): CallDetector.Edge = when (this) {
    TelephonyManager.CALL_STATE_RINGING -> CallDetector.Edge.Ringing(callId, number, null)
    TelephonyManager.CALL_STATE_OFFHOOK -> CallDetector.Edge.OffHook(callId)
    else -> CallDetector.Edge.Idle(callId)
}
