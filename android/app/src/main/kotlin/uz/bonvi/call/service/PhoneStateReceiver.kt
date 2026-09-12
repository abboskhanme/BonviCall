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
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED &&
            intent.action != ACTION_SUBSCRIPTION_PHONE_STATE
        ) {
            return
        }

        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
        val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
        val subscriptionId = boundary.subscriptionIdFrom(intent)

        // A call means the service should be up. Starting it here is what makes
        // capture survive the app never having been opened since a reboot —
        // and it is done BEFORE the subscription check, because the live
        // source that service registers is the one that will see this call
        // correctly when the broadcast below cannot.
        if (state == TelephonyManager.EXTRA_STATE_RINGING ||
            state == TelephonyManager.EXTRA_STATE_OFFHOOK
        ) {
            CaptureService.start(context)
        }

        if (subscriptionId == null) {
            // ═══ The OVERALL broadcast names no subscription — by design ═══
            // The platform sends the call state twice: once per subscription
            // (`SUBSCRIPTION_PHONE_STATE`, with the id) and once for the
            // device as a whole (`PHONE_STATE`, without it). This receiver
            // listened to the second only, so on a handset whose live source
            // was down every edge reached Guard 1 as unknown and was
            // discarded — 22 times on 2026-09-12. An unlabelled edge is not
            // handled and not counted: the labelled sibling is on its way,
            // and on a single-SIM handset the boundary resolves the label
            // itself. Counting it as a discard was the "cosmetic double
            // count" that hid a real loss.
            Timber.d("Phone-state broadcast without a subscription; waiting for the labelled one")
            return
        }

        // The OS gives no call id on this broadcast. The subscription plus the
        // state transition identifies the call for as long as it is in flight,
        // and the durable identity is `client_call_id`, derived at the end from
        // call-log-stable facts (§3.10).
        val callId = "sub-${subscriptionId ?: "unknown"}"

        val edge = when (state) {
            TelephonyManager.EXTRA_STATE_RINGING ->
                CallDetector.Edge.Ringing(callId, number, subscriptionId)

            // ⚠️ CARRIES THE SUBSCRIPTION AND THE NUMBER. It was
            // `OffHook(callId)` -- both dropped -- while `Ringing` two lines
            // up passed them. On an OUTGOING call OFFHOOK is the only edge
            // there is (the platform reports IDLE -> OFFHOOK -> IDLE, no
            // RINGING), so every outgoing call reached SubscriptionRule with
            // `subscriptionId = null` and was rejected SUBSCRIPTION_UNKNOWN --
            // fail-closed and correct, against data this receiver had already
            // resolved and then threw away.
            //
            // Measured on a Xiaomi 13 Lite, 2026-09-12: six outgoing calls,
            // six `subscription_unknown` discards, zero captures, on a handset
            // whose own recorder had written all six files.
            //
            // `TelephonyCallbackSource` was given exactly this fix on
            // 2026-09-11 and this sibling was missed -- STATUS.md's rule
            // ("when you are handed one instance of a bug, go looking for its
            // siblings") written down and then not followed.
            TelephonyManager.EXTRA_STATE_OFFHOOK ->
                CallDetector.Edge.OffHook(callId, number, subscriptionId)
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

    }

    companion object {
        /**
         * `PhoneConstants.ACTION_SUBSCRIPTION_PHONE_STATE_CHANGED` — the
         * per-subscription form of the call-state broadcast, sent since
         * Android 5.1 with the same permission gate as `PHONE_STATE` and the
         * only one of the two that carries the subscription. Not in the public
         * SDK, so the string is written out.
         */
        const val ACTION_SUBSCRIPTION_PHONE_STATE = "android.intent.action.SUBSCRIPTION_PHONE_STATE"
    }
}
