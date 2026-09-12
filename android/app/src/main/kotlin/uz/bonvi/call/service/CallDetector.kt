package uz.bonvi.call.service

import android.content.Context
import android.telephony.TelephonyManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CallEvent
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.Decision
import uz.bonvi.call.domain.ObservedCall
import uz.bonvi.call.domain.PrivacyBoundary
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Turns telephony edges into [CallEvent]s (T69, SPEC §7.5).
 *
 * ═══ The privacy boundary applies to DETECTION, not only to recording ══════
 * Guard 1 runs the moment a call is identified, before any field is written.
 * A call on an unregistered SIM — or on a SIM the OS will not identify —
 * **never enters the queue at all**. It is not captured and filtered
 * server-side: `CallStateMachine` reaches `DISCARDED`, the day's counter is
 * incremented, and nothing about that call exists on this phone.
 *
 * That is the difference between a product that respects the boundary and one
 * that claims to. The employee's private calls are on the same handset.
 *
 * ═══ What this class is not ════════════════════════════════════════════════
 * It holds no Android callback of its own — `PhoneStateReceiver` and
 * `TelephonyCallbackSource` feed it, so the same logic runs on API 26 and on
 * API 31+ where the old listener is deprecated. Every decision here is made
 * from data, which is what lets it be tested without a phone.
 */
@Singleton
class CallDetector @Inject constructor(
    @ApplicationContext private val context: Context,
    private val boundary: PrivacyBoundary,
    private val sessions: CallSessionManager,
    private val pending: PendingCallStore,
    private val onCallEnded: CallEndedListener,
    private val capture: CallCapture,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** What the OS told us, normalised across the two callback APIs. */
    sealed interface Edge {
        data class Ringing(val callId: String, val remoteNumber: String?, val subscriptionId: Int?) : Edge
        data class Dialing(val callId: String, val remoteNumber: String?, val subscriptionId: Int?) : Edge
        /**
         * The call is connected.
         *
         * Carries the number and subscription because **on an outgoing call
         * this is the FIRST edge there is**: the platform reports
         * `IDLE → OFFHOOK → IDLE` with no `RINGING`, so if this edge cannot
         * open a session, an outgoing call is never seen live at all. It
         * could not, until 2026-09-11 — see [handle].
         */
        data class OffHook(
            val callId: String,
            val remoteNumber: String? = null,
            val subscriptionId: Int? = null,
        ) : Edge
        data class Idle(val callId: String) : Edge
    }

    fun onEdge(edge: Edge, scope: CoroutineScope) {
        scope.launch(io) { handle(edge) }
    }

    suspend fun handle(edge: Edge) {
        when (edge) {
            is Edge.Ringing -> begin(
                edge.callId, CallDirection.INCOMING, edge.remoteNumber, edge.subscriptionId,
            )

            is Edge.Dialing -> begin(
                edge.callId, CallDirection.OUTGOING, edge.remoteNumber, edge.subscriptionId,
            )

            is Edge.OffHook -> {
                // ⚠️ An OFFHOOK with no session open is an OUTGOING call.
                //
                // The platform reports an outgoing call as IDLE → OFFHOOK →
                // IDLE: there is no RINGING, and `Edge.Dialing` — the case
                // written for this — was produced by nothing. Neither source
                // emitted it, so `pending.get` returned null here and the
                // branch simply returned. **Every outgoing call was invisible
                // to live capture**, and arrived hours later from the call-log
                // sweep with `app_not_running`, which reads as a dead app
                // rather than a missing branch.
                //
                // Measured on a Xiaomi 13 Lite on 2026-09-11: three outgoing
                // test calls, three sweep recoveries, no live session. It is
                // also what CallSentry does — OFFHOOK without a prior RINGING
                // is an outgoing call — and that app works on this fleet.
                if (pending.get(edge.callId) == null) {
                    begin(
                        edge.callId,
                        CallDirection.OUTGOING,
                        edge.remoteNumber,
                        edge.subscriptionId,
                    )
                }
                // Still absent means the privacy boundary refused it, which is
                // a decision and not a failure: fail closed, capture nothing.
                val call = pending.get(edge.callId) ?: return
                pending.put(call.copy(answeredAtEpochMillis = Clock.epochMillis()))
                sessions.onEvent(edge.callId, CallEvent.Answered)
                // Recording starts HERE, not at the first ring: an unanswered
                // call has no conversation to record — it ships as
                // `not_expected` — and a recorder started against a ringtone
                // competes with the dialler for the microphone.
                capture.start(edge.callId)
            }

            is Edge.Idle -> end(edge.callId)
        }
    }

    private suspend fun begin(
        callId: String,
        direction: CallDirection,
        remoteNumber: String?,
        subscriptionId: Int?,
    ) {
        if (pending.get(callId) != null) return // a repeated edge, not a new call

        sessions.onEvent(callId, CallEvent.Detected)

        // Guard 1, before anything is written. An unidentifiable subscription
        // is a rejection, never a guess.
        val observed = ObservedCall(
            subscriptionId = subscriptionId,
            phoneAccountId = null,
            direction = direction,
            startedAtEpochMillis = Clock.epochMillis(),
            answeredAtEpochMillis = null,
            endedAtEpochMillis = null,
        )
        when (val decision = boundary.evaluate(observed.copy(endedAtEpochMillis = Long.MAX_VALUE))) {
            is Decision.Reject -> {
                // Nothing is stored. The counter is the only trace, and it is
                // reported in the call-log delta so the fleet's unknowns are
                // visible rather than becoming uploads (SPEC §4.4).
                pending.countDiscarded(decision.reason)
                sessions.onEvent(callId, CallEvent.Rejected(decision.reason))
                // Nothing was prepared, so nothing can start. Said explicitly
                // because "the recorder is simply never asked" is the property
                // the privacy boundary rests on.
                capture.discard(callId)
                Timber.i("Call discarded before capture: %s", decision.reason.wire)
            }

            is Decision.Capture -> {
                pending.put(
                    PendingCall(
                        callId = callId,
                        direction = direction,
                        remoteNumber = remoteNumber,
                        registeredNumber = decision.registeredNumber,
                        subscriptionId = decision.subscriptionId,
                        startedAtEpochMillis = observed.startedAtEpochMillis,
                        startedElapsedMillis = Clock.elapsedRealtimeMillis(),
                        answeredAtEpochMillis = null,
                    ),
                )
                // The proof travels with the call: a router can only be built
                // from a Decision.Capture, so a call that reached here is the
                // only kind that can ever be recorded.
                capture.prepare(callId, decision)
                sessions.onEvent(
                    callId,
                    if (direction == CallDirection.INCOMING) {
                        CallEvent.Ringing(CallDirection.INCOMING)
                    } else {
                        CallEvent.Ringing(CallDirection.OUTGOING)
                    },
                )
            }
        }
    }

    private suspend fun end(callId: String) {
        val call = pending.get(callId) ?: return

        // Stop first, write second. The outcome goes onto the pending row
        // rather than into memory because the service is killed between a call
        // ending and its audio being queued on most of this fleet — and what
        // would be lost is the recording of a call that happened.
        val outcome = capture.stop(callId)
        pending.put(
            call.copy(
                endedAtEpochMillis = Clock.epochMillis(),
                audioPath = outcome?.file?.path,
                captureRoute = outcome?.route,
                audioReason = outcome?.reason,
            ),
        )
        sessions.onEvent(callId, CallEvent.Hungup)

        // The record is not built here, and the scheduling is not done here
        // either. The call-log row appears AFTER the call, and
        // `client_call_id` must be derived from the log's DATE where one exists
        // (§3.10 rule 1) — so the sweep does it, twenty seconds later, and the
        // record is right the first time instead of being corrected afterwards.
        //
        // The listener is injected rather than called directly so this class
        // stays free of WorkManager: every decision in it is testable without
        // an Android runtime, which is the only reason the privacy-boundary
        // branches have tests at all.
        onCallEnded.onCallEnded()
    }

    /** The current call state, for the `phone_state` capability check. */
    fun currentCallState(): Int =
        @Suppress("DEPRECATION")
        context.getSystemService(TelephonyManager::class.java)?.callState
            ?: TelephonyManager.CALL_STATE_IDLE
}

/**
 * A call in flight, with everything needed to build its record once it ends.
 *
 * `startedElapsedMillis` is the MONOTONIC reading. Durations come from it, never
 * from subtracting two wall-clock times (CONVENTIONS.md §6) — a user changing
 * the clock mid-call would otherwise produce a negative call length.
 */
data class PendingCall(
    val callId: String,
    val direction: CallDirection,
    val remoteNumber: String?,
    val registeredNumber: String,
    val subscriptionId: Int,
    val startedAtEpochMillis: Long,
    val startedElapsedMillis: Long,
    val answeredAtEpochMillis: Long?,
    val endedAtEpochMillis: Long? = null,
    /** Where the recording is, once the call has ended. */
    val audioPath: String? = null,
    /** Which route produced it — it decides whether the file is ours to delete
     *  (an OEM-harvested file never is, CONVENTIONS.md §8.3). */
    val captureRoute: CaptureRoute? = null,
    /** Why there is no file, from the closed enum. Never free text (N5). */
    val audioReason: AudioMissingReason? = null,
)

/** Where in-flight calls live between edges. Keyed by call id, so call waiting
 *  is two calls rather than one overwritten one (R5). */
interface PendingCallStore {
    suspend fun get(callId: String): PendingCall?
    suspend fun put(call: PendingCall)
    suspend fun remove(callId: String)
    suspend fun all(): List<PendingCall>

    /** A call the boundary refused. Counted, never stored. */
    suspend fun countDiscarded(reason: uz.bonvi.call.domain.RejectReason)
}

/**
 * Told when a call has ended, so something else can schedule the sweep.
 *
 * A `fun interface` rather than a direct `WorkManager` call from [CallDetector]:
 * the detector's job is deciding, not scheduling, and a class that touches
 * WorkManager cannot be unit-tested — which would mean the privacy-boundary
 * branches had no tests, and those are the ones that must not be got wrong.
 */
fun interface CallEndedListener {
    fun onCallEnded()
}
