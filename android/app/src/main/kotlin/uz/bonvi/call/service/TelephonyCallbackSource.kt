package uz.bonvi.call.service

import android.content.Context
import android.telephony.TelephonyManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.core.Clock
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
    private val enrolment: uz.bonvi.call.capture.EnrolmentFacts,
) {

    private var registered: Any? = null

    fun register(scope: CoroutineScope) {
        if (registered != null) return
        val telephony = context.getSystemService(TelephonyManager::class.java) ?: return

        @Suppress("TooGenericExceptionCaught")
        try {
            // ⚠️ Registered ON THE ENROLLED SUBSCRIPTION, not on the default
            // one. The callback API reports only a state — it carries no
            // subscription — so an edge from an unscoped registration reaches
            // the privacy boundary with `subscriptionId = null`, and Guard 1
            // fails closed on exactly that. The result was a live source that
            // fired correctly and had every call refused.
            //
            // Scoping the registration is what makes the id knowable: the
            // callback can only be about the SIM it was registered for.
            val scoped = enrolledSubscription()?.let { subscriptionId ->
                @Suppress("TooGenericExceptionCaught")
                try {
                    telephony.createForSubscriptionId(subscriptionId)
                } catch (error: Exception) {
                    Timber.w(error, "Could not scope telephony to the enrolled SIM")
                    null
                }
            } ?: telephony

            registered = if (Capabilities.supportsTelephonyCallback()) {
                registerModern(scoped, scope)
            } else {
                registerLegacy(scoped, scope)
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
        val callback = ModernCallStateCallback(detector, scope, enrolledSubscription())
        telephony.registerTelephonyCallback(executor, callback)
        return callback
    }

    @Suppress("DEPRECATION")
    private fun registerLegacy(telephony: TelephonyManager, scope: CoroutineScope): Any {
        val listener = LegacyCallStateListener(detector, scope, enrolledSubscription())
        telephony.listen(listener, android.telephony.PhoneStateListener.LISTEN_CALL_STATE)
        return listener
    }

    /** The SIM this installation is bound to, or null before enrolment. */
    private fun enrolledSubscription(): Int? =
        enrolment.current().subscriptionId?.takeIf { it >= 0 }

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
    private val subscriptionId: Int?,
) : android.telephony.TelephonyCallback(),
    android.telephony.TelephonyCallback.CallStateListener {

    private val calls = LiveCallIds()

    override fun onCallStateChanged(state: Int) {
        detector.onEdge(state.toEdge(calls.idFor(state), subscriptionId = subscriptionId), scope)
    }
}

/** Below API 31. Deprecated and unavoidable. */
@Suppress("DEPRECATION")
private class LegacyCallStateListener(
    private val detector: CallDetector,
    private val scope: CoroutineScope,
    private val subscriptionId: Int?,
) : android.telephony.PhoneStateListener() {

    private val calls = LiveCallIds()

    override fun onCallStateChanged(state: Int, phoneNumber: String?) {
        detector.onEdge(state.toEdge(calls.idFor(state), phoneNumber, subscriptionId), scope)
    }
}

/**
 * Keeps one id for the length of one call.
 *
 * A new id is minted on the first non-IDLE state and held until IDLE, so every
 * edge of a call carries the same key and the next call gets its own. Not
 * thread-safe by construction and it does not need to be: the callback is
 * registered with a single-threaded executor and the platform delivers call
 * states in order.
 */
private class LiveCallIds {
    private var current: String? = null

    fun idFor(state: Int): String {
        if (state == TelephonyManager.CALL_STATE_IDLE) {
            // The id the call has been using, then release it. Falling back to
            // a fresh one keeps `end()` addressable even if the process was
            // started mid-call.
            return (current ?: newLiveCallId()).also { current = null }
        }
        return current ?: newLiveCallId().also { current = it }
    }
}

/**
 * One id per live call, minted when a call starts.
 *
 * ⚠️ This was the constant `"live"`, shared by every call the live source ever
 * saw, with the note that it reused "the manifest receiver's key so the two
 * sources address the same in-flight call". They never did: the receiver's key
 * is `sub-<subscriptionId>`, a different string — and on API 31+ the receiver
 * is refused the broadcast entirely, so there is no second source to agree
 * with.
 *
 * What the shared constant did instead was collide every call with the last
 * one. The capture file is named from the id, so `live-app_mic.m4a` was
 * **overwritten by the next call**, and the previous call — already queued —
 * shipped with `recording_route_unavailable` while a perfectly good recording
 * of the wrong conversation sat on disk. Measured on a Xiaomi 13 Lite,
 * 2026-09-11.
 *
 * Minted from the monotonic clock, so it is unique, ordered, and unaffected by
 * the phone syncing its wall clock mid-call.
 */
private fun newLiveCallId(): String = "live-${Clock.elapsedRealtimeMillis()}"

private fun Int.toEdge(
    callId: String,
    number: String? = null,
    subscriptionId: Int? = null,
): CallDetector.Edge = when (this) {
    TelephonyManager.CALL_STATE_RINGING ->
        CallDetector.Edge.Ringing(callId, number, subscriptionId)

    // Carries the subscription now, because on an outgoing call this is the
    // first edge there is and the one that has to open the session.
    TelephonyManager.CALL_STATE_OFFHOOK ->
        CallDetector.Edge.OffHook(callId, number, subscriptionId)

    else -> CallDetector.Edge.Idle(callId)
}
