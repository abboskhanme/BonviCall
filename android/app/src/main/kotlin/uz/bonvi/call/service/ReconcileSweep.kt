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
    /** Resolves the remote number to a contact name FRESH, per call. Injected
     *  here rather than called at capture time so the name reflects the phone
     *  book as it stands when the record is built -- the whole reason this
     *  product exists (Moi Zvonki cached the first name and never updated it). */
    private val contactNames: uz.bonvi.call.capture.ContactNameResolver,
    /** The handset's own recordings, for a call the live path missed — see
     *  [harvestForRecovered]. The same locator, behind the same proof, that
     *  the live route uses. */
    private val oemRecordings: uz.bonvi.call.capture.OemRecordingLocator,
    private val captureCapabilities: uz.bonvi.call.capture.CaptureCapabilityChecker,
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
                    // The log decides whether anybody ANSWERED. The live path
                    // took OFFHOOK for the answer, and on an outgoing call
                    // OFFHOOK is dialling: a 0-second call shipped as
                    // `answered`, the server refused it by constraint, and its
                    // ring-tone recording sat in the queue behind the refusal.
                    val answeredAt = ReconcileRule.answeredAt(
                        liveAnsweredAtEpochMillis = call.answeredAtEpochMillis,
                        logStartedAtEpochMillis = match.startedAtEpochMillis,
                        logDurationSec = match.durationSec,
                    )
                    val logged = call.copy(
                        remoteNumber = call.remoteNumber ?: match.remoteNumber,
                        answeredAtEpochMillis = answeredAt,
                    )
                    enqueue(
                        queued = if (answeredAt == null) withoutRecording(logged) else logged,
                        endedAt = match.endedAtEpochMillis,
                        reconciledStartedAt = match.startedAtEpochMillis,
                        source = CallSource.LIVE_CAPTURE,
                        durationSec = match.durationSec,
                    )
                    reconciled++
                }

                ReconcileRule.deadlinePassed(call.endedAtEpochMillis ?: now, now) -> {
                    // Fifteen minutes and no row. Upload it anyway with the id
                    // derived from the live time (§3.10 rule 2) — a call is
                    // never dropped because the log was slow.
                    enqueue(
                        queued = call,
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
        //
        // ⚠️ Once. A row this sweep has already handled — matched to a live
        // call, or recovered — is never handled again, and the WATERMARK is
        // what remembers that across sweeps. Without it every run re-queued
        // every row in the two-day lookback as `call_log_recovery`, and since
        // `source` and `audio_missing_reason` are correctable server-side, a
        // call the live path had captured (audio job queued, `pending_upload`)
        // was rewritten as `app_not_running` half an hour later. Three of the
        // day's five recorded calls read that way on the panel (2026-09-12).
        // The re-sends also cost data on every sweep and were the source of
        // the REPLACE that cancelled running upload passes.
        //
        // The watermark advances only over rows the app has actually handled,
        // so a row Guard 1 refuses is looked at again (cheap) and a row for a
        // call still in flight cannot be skipped: its row does not exist yet.
        val registeredKey = Phone.phoneKey(registered)
        val watermark = session.snapshot.recoveryWatermarkEpochMillis
        var handledUpTo = watermark
        var recovered = 0
        for (entry in entries) {
            if (entry.startedAtEpochMillis in matchedEntries) {
                handledUpTo = maxOf(handledUpTo, entry.startedAtEpochMillis)
                continue
            }
            if (finished.any { it.startedAtEpochMillis == entry.startedAtEpochMillis }) continue
            if (entry.startedAtEpochMillis <= watermark) continue

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
                queued = recoveredCall,
                endedAt = entry.endedAtEpochMillis,
                reconciledStartedAt = entry.startedAtEpochMillis,
                source = CallSource.CALL_LOG_RECOVERY,
                // There was never any audio to capture: the app was not
                // running. Naming it correctly is what stops the gap report
                // blaming the handset's recorder.
                recoveryReason = AudioMissingReason.APP_NOT_RUNNING,
                durationSec = entry.durationSec,
            )
            recovered++
            handledUpTo = maxOf(handledUpTo, entry.startedAtEpochMillis)
        }
        if (handledUpTo > watermark) session.saveRecoveryWatermark(handledUpTo)

        Timber.i(
            "Sweep: %d reconciled, %d recovered, %d still waiting for a log row",
            reconciled, recovered, waiting,
        )
        return Result(reconciled, recovered, waiting)
    }

    /**
     * The handset's own recording of a call the app did not see live.
     *
     * ═══ Why this is allowed, and what bounds it ═══════════════════════════
     * The live route is `OemHarvestStrategy`, which only ever scans behind a
     * [uz.bonvi.call.domain.Decision.Capture]. A recovered call has passed the
     * same Guard 1 (the recovery pass filtered it by subscription against the
     * call log's own attribution column), so the same proof can be built and
     * the same locator asked — the window is the call's own log row, not a
     * live edge, and it is exactly as narrow. Nothing here writes to, moves or
     * deletes the file (CONVENTIONS.md §8.3); `AudioPipeline` never deletes an
     * OEM-route file either.
     *
     * Measured need (2026-09-12): the live source was down after an update,
     * the CEO's test call was discarded, the sweep recovered it as
     * `app_not_running` — and the handset's own both-voices recording of it
     * sat in `MIUI/sound_recorder/call_rec`, unread.
     */
    private fun harvestForRecovered(call: PendingCall, endedAt: Long): java.io.File? {
        val answeredAt = call.answeredAtEpochMillis ?: return null // nobody answered: no conversation
        if (!captureCapabilities.oemRecorderReachable()) return null
        @Suppress("TooGenericExceptionCaught")
        return try {
            oemRecordings.locate(
                uz.bonvi.call.domain.Decision.Capture(
                    subscriptionId = call.subscriptionId,
                    registeredNumber = call.registeredNumber,
                    answeredAtEpochMillis = answeredAt,
                    endedAtEpochMillis = endedAt,
                ),
            )
        } catch (error: Exception) {
            // A refused listing is a call without audio, never a lost call.
            Timber.w(error, "OEM harvest for a recovered call refused")
            null
        }
    }

    /**
     * A call nobody answered has no conversation, so its recording is the
     * ring tone (the app's own mic, started at dialling) and is discarded
     * here — ours to delete, never an OEM file (CONVENTIONS.md §8.3), and the
     * handset's recorder does not write one for an unanswered call anyway.
     */
    private fun withoutRecording(call: PendingCall): PendingCall {
        val path = call.audioPath
        if (path != null && call.captureRoute != CaptureRoute.OEM_FILE_HARVEST) {
            java.io.File(path).delete()
        }
        return call.copy(audioPath = null, captureRoute = null, audioReason = null)
    }

    @Suppress("LongParameterList")
    private suspend fun enqueue(
        queued: PendingCall,
        endedAt: Long,
        reconciledStartedAt: Long?,
        source: CallSource,
        recoveryReason: AudioMissingReason? = null,
        durationSec: Int? = null,
    ) {
        // What capture actually produced, written onto the pending row when the
        // call ended. `NONE` with the recorder's own reason is the honest
        // answer for a call that produced nothing.
        //
        // A RECOVERED call never had the app's recorder running — but on a
        // handset whose own recorder is on, the file is in the folder anyway,
        // and the OEM route is post-hoc by nature. So it is asked for here,
        // behind the same proof as the live route, and a call the live path
        // missed still arrives with both voices rather than `app_not_running`.
        val harvested = if (source == CallSource.CALL_LOG_RECOVERY) harvestForRecovered(queued, endedAt) else null
        val call = if (harvested != null) {
            queued.copy(
                audioPath = harvested.path,
                captureRoute = CaptureRoute.OEM_FILE_HARVEST,
                audioReason = null,
            )
        } else {
            queued
        }
        val reason = if (harvested != null) null else recoveryReason
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
            // FRESH, every time. The call already passed Guard 1 (it is in
            // `pending`, or it was filtered by subscription in the recovery
            // pass), so reconstructing the proof here is legitimate -- and the
            // resolver refuses to look up a name without it (N28).
            contactName = contactNames.resolve(
                capture = uz.bonvi.call.domain.Decision.Capture(
                    subscriptionId = call.subscriptionId,
                    registeredNumber = call.registeredNumber,
                    answeredAtEpochMillis = call.answeredAtEpochMillis ?: call.startedAtEpochMillis,
                    endedAtEpochMillis = endedAt,
                ),
                remoteNumber = call.remoteNumber,
            ),
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
        contactName = contactName,
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
