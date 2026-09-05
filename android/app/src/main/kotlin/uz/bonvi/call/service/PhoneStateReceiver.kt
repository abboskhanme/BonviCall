package uz.bonvi.call.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import timber.log.Timber
import uz.bonvi.call.capture.SubscriptionPrivacyBoundary
import uz.bonvi.call.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import javax.inject.Inject

/**
 * The call detector's ears (T69).
 *
 * `ACTION_PHONE_STATE_CHANGED` is a manifest-registered broadcast, so it
 * arrives even when the app is not running — which is the point: the first
 * thing that happens after a reboot is often a call, and a listener registered
 * only from a live service would miss it.
 *
 * ═══ Why a receiver and not only a TelephonyCallback ═══════════════════════
 * `PhoneStateListener` is deprecated at API 31 and `TelephonyCallback` needs a
 * registered listener, i.e. a running process. The broadcast covers the cold
 * case; `TelephonyCallbackSource` covers the live one with better data (it
 * carries the subscription directly). Both funnel into one [CallDetector], so
 * the RULES exist once and are testable without a phone.
 *
 * The outgoing number arrives on `ACTION_NEW_OUTGOING_CALL` on older releases
 * and not at all on newer ones; a missing number is not a reason to drop the
 * call — the reconciliation sweep (T67) fills it in from the call log, and
 * `client_call_id` treats an unknown remote as a stable `unknown` (§3.10).
 */
@AndroidEntryPoint
class PhoneStateReceiver : BroadcastReceiver() {

    @Inject lateinit var detector: CallDetector

    @Inject lateinit var boundary: SubscriptionPrivacyBoundary

    @Inject @IoDispatcher lateinit var io: CoroutineDispatcher

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return

        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
        val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
        val subscriptionId = boundary.subscriptionIdFrom(intent)

        // The OS gives no call id on this broadcast. The subscription plus the
        // state transition identifies the call for as long as it is in flight,
        // and the durable identity is `client_call_id`, derived at the end from
        // call-log-stable facts (§3.10).
        val callId = "sub-${subscriptionId ?: "unknown"}"

        val edge = when (state) {
            TelephonyManager.EXTRA_STATE_RINGING ->
                CallDetector.Edge.Ringing(callId, number, subscriptionId)

            TelephonyManager.EXTRA_STATE_OFFHOOK -> CallDetector.Edge.OffHook(callId)
            TelephonyManager.EXTRA_STATE_IDLE -> CallDetector.Edge.Idle(callId)
            else -> null
        } ?: return

        // goAsync: the edge has to be recorded before the receiver returns, or
        // the process can be killed between the broadcast and the write and the
        // call is lost. Ten seconds is the broadcast budget; this work is a
        // DataStore read and a Room write.
        val result = goAsync()
        CoroutineScope(SupervisorJob() + io).launch {
            @Suppress("TooGenericExceptionCaught")
            try {
                detector.handle(edge)
            } catch (error: Exception) {
                // Broad, and the specific failure it catches is a telephony or
                // storage error during a live call. Losing the edge is bad;
                // crashing the phone's broadcast dispatch is worse, and it is
                // the kind of thing an OEM reports to the user.
                Timber.e(error, "Failed to handle a phone-state edge")
            } finally {
                result.finish()
            }
        }

        // A call means the service should be up. Starting it here is what makes
        // capture survive the app never having been opened since a reboot.
        if (state == TelephonyManager.EXTRA_STATE_RINGING ||
            state == TelephonyManager.EXTRA_STATE_OFFHOOK
        ) {
            CaptureService.start(context)
        }
    }
}
