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

    /** Which subscription [registered] is scoped to, so a change forces a
     *  re-registration rather than being silently ignored. */
    private var registeredSubscriptionId: Int? = null

    /**
     * Register the live source, or decline to.
     *
     * ═══ Why this refuses to register without an enrolled SIM ══════════════
     * The callback API reports a STATE and nothing else, so the subscription
     * an edge belongs to can only come from the registration being scoped to
     * it. Two things followed from getting that wrong, and both were measured
     * on a Xiaomi 13 Lite on 2026-09-12:
     *
     *  • `CaptureService` starts DURING enrolment, before E4 has saved the
     *    SIM, so the scoping fell through to the unscoped manager and the id
     *    handed to the callback was null. `register()` then returned early for
     *    the life of the process, so it was never re-read. Six outgoing calls,
     *    six SUBSCRIPTION_UNKNOWN discards, on a handset that had recorded all
     *    six.
     *  • Labelling an UNSCOPED stream with the enrolled id would be worse than
     *    the bug: on a dual-SIM handset it attributes the employee's private
     *    calls to the work SIM and uploads them. So an unscoped registration is
     *    refused outright rather than made to guess.
     *
     * ═══ And why it takes the id as a parameter ════════════════════════════
     * Declining was only safe if something called again once the SIM was
     * known, and nothing did: the one caller was `CaptureService.onCreate`,
     * which runs before `SessionStore` has loaded its DataStore snapshot, so
     * `enrolledSubscription()` answered null on every process start, the
     * source declined, and no retry ever came. Measured 2026-09-12 after an
     * update: `dumpsys telephony.registry` showed ZERO registrations for the
     * app, every call fell to the manifest receiver, and on this handset the
     * receiver's broadcast carries no subscription — so the CEO's test call
     * was discarded `subscription_unknown` on a phone that had captured the
     * previous one. The service now re-registers from the SIM flow itself and
     * passes the id it just observed, so the snapshot's timing no longer
     * decides whether calls are captured.
     */
    @Synchronized
    fun register(scope: CoroutineScope, enrolledSubscriptionId: Int? = enrolledSubscription()) {
        val enrolled = enrolledSubscriptionId
        if (enrolled == null) {
            Timber.i("Live call source: no enrolled SIM yet, not registering")
            return
        }
        if (registered != null && registeredSubscriptionId == enrolled) return
        if (registered != null) unregister()

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
            val scoped = @Suppress("TooGenericExceptionCaught") try {
                telephony.createForSubscriptionId(enrolled)
            } catch (error: Exception) {
                Timber.w(error, "Could not scope telephony to the enrolled SIM")
                null
            }
            if (scoped == null) {
                // Unscoped would mean labelling another SIM's calls as ours.
                // The receiver path remains; this one stays off.
                return
            }

            registered = if (Capabilities.supportsTelephonyCallback()) {
                registerModern(scoped, scope, enrolled)
            } else {
                registerLegacy(scoped, scope, enrolled)
            }
            registeredSubscriptionId = enrolled
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
    private fun registerModern(
        telephony: TelephonyManager,
        scope: CoroutineScope,
        subscriptionId: Int,
    ): Any {
        val executor = Executor { it.run() }
        val callback = ModernCallStateCallback(detector, scope, subscriptionId)
        telephony.registerTelephonyCallback(executor, callback)
        return callback
    }

    @Suppress("DEPRECATION")
    private fun registerLegacy(
        telephony: TelephonyManager,
        scope: CoroutineScope,
        subscriptionId: Int,
    ): Any {
        val listener = LegacyCallStateListener(detector, scope, subscriptionId)
        telephony.listen(listener, android.telephony.PhoneStateListener.LISTEN_CALL_STATE)
        return listener
    }

    /** The SIM this installation is bound to, or null before enrolment. */
    private fun enrolledSubscription(): Int? =
        enrolment.current().subscriptionId?.takeIf { it >= 0 }

    @Synchronized
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
        registeredSubscriptionId = null
    }
}

/** API 31+. Not deprecated, and registered per subscription. */
@androidx.annotation.RequiresApi(android.os.Build.VERSION_CODES.S)
private class ModernCallStateCallback(
    private val detector: CallDetector,
    private val scope: CoroutineScope,
    /** The subscription this callback's registration is SCOPED to, so
     *  labelling every edge with it is a fact rather than a guess. */
    private val subscriptionId: Int,
) : android.telephony.TelephonyCallback(),
    android.telephony.TelephonyCallback.CallStateListener {

    private val calls = LiveCallIds()

    override fun onCallStateChanged(state: Int) {
        detector.onEdge(
            state.toEdge(calls.idFor(state), subscriptionId = subscriptionId),
            scope,
        )
    }
}

/** Below API 31. Deprecated and unavoidable. */
@Suppress("DEPRECATION")
private class LegacyCallStateListener(
    private val detector: CallDetector,
    private val scope: CoroutineScope,
    /** Scoped, as on [ModernCallStateCallback]. */
    private val subscriptionId: Int,
) : android.telephony.PhoneStateListener() {

    private val calls = LiveCallIds()

    override fun onCallStateChanged(state: Int, phoneNumber: String?) {
        detector.onEdge(
            state.toEdge(calls.idFor(state), phoneNumber, subscriptionId),
            scope,
        )
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
