package uz.bonvi.call.service

import com.squareup.moshi.Moshi
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.remote.dto.DeviceCallIn
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallEvent
import uz.bonvi.call.domain.CallSource
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.ClientCallId
import uz.bonvi.call.domain.ReconcileRule
import uz.bonvi.call.core.Phone
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The recovery sweep (T67, UC-13).
 *
 * Two jobs, and the second is the one that matters most:
 *
 * 1. **Reconcile** finished calls against the call log, so the record carries
 *    the direction, disposition, start time and duration the phone actually
 *    recorded — and so `client_call_id` is derived from the log's `DATE`, the
 *    only timestamp two independent installs agree on (§3.10 rule 1).
 *
 * 2. **Recover** calls that happened while the app was dead. A phone whose
 *    service was killed overnight still made calls, and without this they
 *    simply do not exist. They are queued with `source = call_log_recovery` and
 *    `audio_missing_reason = app_not_running`, which is the honest reason:
 *    there was never any audio to capture.
 *
 * ═══ The privacy boundary applies here too ═════════════════════════════════
 * A recovered call is filtered by the SAME Guard 1 rule as a live one. The call
 * log contains the employee's private calls, so a sweep that queued everything
 * it found would be a bigger leak than a missed detection — it would upload
 * calls the live path had correctly refused.
 *
 * **The sweep never invents rows.** If the call log itself was cleared, it
 * reports the gap rather than filling it (SPEC §7.5).
 */
@Singleton
class ReconcileSweep @Inject constructor(
    private val callLog: CallLogReader,
    private val pending: PendingCallStore,
    private val sessions: CallSessionManager,
    private val queue: CallQueueRepository,
    private val audioJobs: uz.bonvi.call.data.repository.AudioJobRepository,
    private val session: SessionStore,
    private val moshi: Moshi,
) {

    data class Result(val reconciled: Int, val recovered: Int, val stillWaiting: Int)

    suspend fun run(sinceEpochMillis: Long): Result {
        val registered = session.snapshot.registeredNumberE164 ?: return Result(0, 0, 0)
        val subscriptionId = session.snapshot.simSubscriptionId ?: return Result(0, 0, 0)

        val entries = callLog.since(sinceEpochMillis)
        val now = Clock.epochMillis()
        var reconciled = 0
        var waiting = 0

        // ── 1. Finished live calls ────────────────────────────────────────
        val finished = pending.all().filter { it.endedAtEpochMillis != null }
        val matchedEntries = mutableSetOf<Long>()
        for (call in finished) {
            val match = ReconcileRule.match(
                live = ReconcileRule.Candidate(
                    call.startedAtEpochMillis, call.direction, call.remoteNumber,
                ),
                entries = entries,
                startedAt = { it.startedAtEpochMillis },
                direction = { it.direction },
                remoteNumber = { it.remoteNumber },
            )

            when {
                match != null -> {
                    matchedEntries += match.startedAtEpochMillis
                    enqueue(
                        call = call.copy(remoteNumber = call.remoteNumber ?: match.remoteNumber),
                        endedAt = match.endedAtEpochMillis,
                        reconciledStartedAt = match.startedAtEpochMillis,
                        source = CallSource.LIVE_CAPTURE,
                    )
                    reconciled++
                }

                ReconcileRule.deadlinePassed(call.endedAtEpochMillis ?: now, now) -> {
                    // Fifteen minutes and no row. Upload it anyway with the id
                    // derived from the live time (§3.10 rule 2) — a call is
                    // never dropped because the log was slow.
                    enqueue(
                        call = call,
                        endedAt = call.endedAtEpochMillis ?: now,
                        reconciledStartedAt = null,
                        source = CallSource.LIVE_CAPTURE,
                    )
                    reconciled++
                }

                else -> waiting++
            }
        }

        // ── 2. Calls the app never saw ────────────────────────────────────
        val registeredKey = Phone.phoneKey(registered)
        var recovered = 0
        for (entry in entries) {
            if (entry.startedAtEpochMillis in matchedEntries) continue
            if (finished.any { it.startedAtEpochMillis == entry.startedAtEpochMillis }) continue

            // Guard 1 again. The call log holds the employee's private calls;
            // a sweep that queued everything would upload what the live path
            // correctly refused.
            val entrySubscription = entry.phoneAccountId?.trim()?.toIntOrNull()
            if (entrySubscription != null && entrySubscription != subscriptionId) continue
            if (entrySubscription == null && registeredKey == null) continue

            val recoveredCall = PendingCall(
                callId = "recovered-${entry.startedAtEpochMillis}",
                direction = entry.direction,
                remoteNumber = entry.remoteNumber,
                registeredNumber = registered,
                subscriptionId = subscriptionId,
                startedAtEpochMillis = entry.startedAtEpochMillis,
                startedElapsedMillis = 0L,
                answeredAtEpochMillis = if (entry.durationSec > 0) {
                    entry.startedAtEpochMillis
                } else {
                    null
                },
                endedAtEpochMillis = entry.endedAtEpochMillis,
            )
            enqueue(
                call = recoveredCall,
                endedAt = entry.endedAtEpochMillis,
                reconciledStartedAt = entry.startedAtEpochMillis,
                source = CallSource.CALL_LOG_RECOVERY,
                // There was never any audio to capture: the app was not
                // running. Naming it correctly is what stops the gap report
                // blaming the handset's recorder.
                reason = AudioMissingReason.APP_NOT_RUNNING,
                durationSec = entry.durationSec,
            )
            recovered++
        }

        Timber.i(
            "Sweep: %d reconciled, %d recovered, %d still waiting for a log row",
            reconciled, recovered, waiting,
        )
        return Result(reconciled, recovered, waiting)
    }

    @Suppress("LongParameterList")
    private suspend fun enqueue(
        call: PendingCall,
        endedAt: Long,
        reconciledStartedAt: Long?,
        source: CallSource,
        reason: AudioMissingReason? = null,
        durationSec: Int? = null,
    ) {
        // What capture actually produced, written onto the pending row when the
        // call ended. `NONE` with the recorder's own reason is the honest
        // answer for a call that produced nothing — and for a recovered call,
        // which never had a recorder running at all.
        val captured = call.audioPath?.let { java.io.File(it) }?.takeIf { it.isFile }
        val record = CallRecordBuilder.build(
            call = call,
            endedAtEpochMillis = endedAt,
            endedElapsedMillis = call.startedElapsedMillis +
                (durationSec?.times(1000L) ?: (endedAt - call.startedAtEpochMillis)),
            captureRoute = if (captured != null) {
                call.captureRoute ?: CaptureRoute.NONE
            } else {
                CaptureRoute.NONE
            },
            captureReason = reason ?: call.audioReason,
            source = source,
            reconciledStartedAtEpochMillis = reconciledStartedAt,
        )
        val payload = moshi.adapter(DeviceCallIn::class.java).toJson(record.toWire())
        queue.enqueue(record.clientCallId, payload)

        // The recording can only be queued NOW: `client_call_id` is derived
        // from the reconciled start time, and the server accepts audio only
        // against a call it already holds. Before this line the app recorded
        // calls it never uploaded.
        if (captured != null && call.captureRoute != null) {
            audioJobs.enqueue(
                clientCallId = record.clientCallId,
                path = captured.path,
                captureRoute = call.captureRoute,
                recordedAtEpochMillis = call.answeredAtEpochMillis ?: call.startedAtEpochMillis,
            )
        }
        // The id is stable, so a repeat of the same call is the same row: the
        // sweep can run as often as it likes without duplicating anything (N2).
        pending.remove(call.callId)
        sessions.onEvent(call.callId, CallEvent.MetadataQueued)
        sessions.onEvent(
            call.callId,
            CallEvent.AudioMissing(record.audioMissingReason),
        )
    }

    private fun uz.bonvi.call.domain.CallRecord.toWire(): DeviceCallIn = DeviceCallIn(
        clientCallId = java.util.UUID.fromString(clientCallId),
        deviceEpochMs = deviceEpochMillis,
        deviceTimezone = deviceTimezone,
        direction = wireDirection(direction),
        disposition = wireDisposition(disposition),
        startedAt = java.time.OffsetDateTime.parse(Clock.toWire(startedAtEpochMillis)),
        answeredAt = answeredAtEpochMillis?.let {
            java.time.OffsetDateTime.parse(Clock.toWire(it))
        },
        endedAt = java.time.OffsetDateTime.parse(Clock.toWire(endedAtEpochMillis)),
        durationSec = durationSec,
        remoteNumber = remoteNumber,
        audioExpected = audioMissingReason == AudioMissingReason.PENDING_UPLOAD,
        audioMissingReason = wireReason(audioMissingReason),
        captureRoute = wireRoute(captureRoute),
        source = wireSource(source),
        reconciledWithCallLog = source == CallSource.CALL_LOG_RECOVERY,
        appVariant = uz.bonvi.call.data.remote.dto.AppVariant.entries
            .first { it.value == uz.bonvi.call.BuildConfig.APP_VARIANT },
        appVersion = uz.bonvi.call.BuildConfig.VERSION_NAME,
    )

    private fun wireDirection(value: CallDirection) =
        uz.bonvi.call.data.remote.dto.CallDirection.entries.first { it.value == value.wire }

    private fun wireDisposition(value: uz.bonvi.call.domain.CallDisposition) =
        uz.bonvi.call.data.remote.dto.CallDisposition.entries.first { it.value == value.wire }

    private fun wireReason(value: AudioMissingReason) =
        uz.bonvi.call.data.remote.dto.AudioMissingReason.entries.first { it.value == value.wire }

    private fun wireRoute(value: CaptureRoute) =
        uz.bonvi.call.data.remote.dto.CaptureRoute.entries.first { it.value == value.wire }

    private fun wireSource(value: CallSource) =
        uz.bonvi.call.data.remote.dto.CallSource.entries.first { it.value == value.wire }
}
