package uz.bonvi.call.service

import uz.bonvi.call.core.Clock
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CallDisposition
import uz.bonvi.call.domain.CallRecord
import uz.bonvi.call.domain.CallSource
import uz.bonvi.call.domain.CaptureRoute
import uz.bonvi.call.domain.ClientCallId

/**
 * Turns a finished [PendingCall] plus a capture outcome into the record that
 * goes on the wire.
 *
 * ═══ Every failure path sets an `audio_missing_reason` (T75, N5) ═══════════
 * The enum has ten values and **one of them is always right**. A call that
 * arrives with no audio and no reason is worse than one that never arrives: it
 * silently inflates the gap report's numerator and points at the wrong handset,
 * so an admin spends an afternoon on a phone that is working.
 *
 * `NOT_EXPECTED` is the one that keeps the denominator honest — an unanswered
 * call has no conversation to record, and colouring it as a capture failure
 * would make a healthy fleet look broken (SPEC §3.9 excludes it and
 * `pending_upload` from the gap report's denominator).
 */
object CallRecordBuilder {

    fun build(
        call: PendingCall,
        endedAtEpochMillis: Long,
        endedElapsedMillis: Long,
        captureRoute: CaptureRoute,
        captureReason: AudioMissingReason?,
        source: CallSource,
        reconciledStartedAtEpochMillis: Long? = null,
    ): CallRecord {
        val answered = call.answeredAtEpochMillis != null
        val duration = if (answered) {
            // The MONOTONIC clock (CONVENTIONS.md §6). Subtracting two
            // wall-clock readings across a clock change gives a negative call.
            Clock.durationSeconds(call.startedElapsedMillis, endedElapsedMillis)
        } else {
            0
        }

        val disposition = when {
            answered -> CallDisposition.ANSWERED
            call.direction == uz.bonvi.call.domain.CallDirection.INCOMING -> CallDisposition.MISSED
            // UC-09: an unanswered outgoing call is never reported as a
            // conversation, and is never dropped either.
            else -> CallDisposition.NO_ANSWER
        }

        // Rule 3 of §3.10: the id is derived once, from the reconciled start
        // time when there is one and from the live time truncated to whole
        // seconds when there is not. A later correction goes to the SAME id.
        val idTimestamp = reconciledStartedAtEpochMillis
            ?: ClientCallId.truncateToSecond(call.startedAtEpochMillis)

        return CallRecord(
            clientCallId = ClientCallId.derive(
                registeredNumber = call.registeredNumber,
                direction = call.direction,
                startedAtEpochMillis = idTimestamp,
                remoteNumber = call.remoteNumber,
            ),
            direction = call.direction,
            disposition = disposition,
            source = source,
            remoteNumber = call.remoteNumber,
            startedAtEpochMillis = reconciledStartedAtEpochMillis ?: call.startedAtEpochMillis,
            answeredAtEpochMillis = call.answeredAtEpochMillis,
            endedAtEpochMillis = endedAtEpochMillis,
            durationSec = duration,
            deviceEpochMillis = Clock.epochMillis(),
            deviceTimezone = Clock.timezoneId(),
            captureRoute = captureRoute,
            audioMissingReason = reasonFor(answered, captureRoute, captureReason),
        )
    }

    /**
     * The reason, never null.
     *
     * Order matters:
     *  1. an unanswered call has nothing to record — `not_expected`, and it is
     *     excluded from the gap report's denominator rather than counted as a
     *     failure;
     *  2. audio was captured and is waiting to go — `pending_upload`, also
     *     excluded;
     *  3. otherwise whatever the capture path reported, and if it reported
     *     nothing at all, `recording_route_unavailable` — the honest answer
     *     while the OEM locators are still `NoOp` (T71b).
     */
    fun reasonFor(
        answered: Boolean,
        captureRoute: CaptureRoute,
        captureReason: AudioMissingReason?,
    ): AudioMissingReason = when {
        !answered -> AudioMissingReason.NOT_EXPECTED
        captureRoute != CaptureRoute.NONE -> AudioMissingReason.PENDING_UPLOAD
        else -> captureReason ?: AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE
    }
}
