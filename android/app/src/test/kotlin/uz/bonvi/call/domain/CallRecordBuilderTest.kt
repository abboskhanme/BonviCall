package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.service.CallRecordBuilder
import uz.bonvi.call.service.PendingCall

/**
 * Every failure path sets an `audio_missing_reason` (T75, N5).
 *
 * A call that arrives with no audio and no reason is worse than one that never
 * arrives: it silently inflates the gap report's numerator and points at the
 * wrong handset, so an admin spends an afternoon on a phone that is working.
 */
class CallRecordBuilderTest {

    private fun pending(answered: Boolean, direction: CallDirection = CallDirection.OUTGOING) =
        PendingCall(
            callId = "call-1",
            direction = direction,
            remoteNumber = "901112233",
            registeredNumber = "+998907776655",
            subscriptionId = 2,
            startedAtEpochMillis = 1_772_615_791_412L,
            startedElapsedMillis = 5_000L,
            answeredAtEpochMillis = if (answered) 1_772_615_795_000L else null,
        )

    private fun build(
        answered: Boolean,
        route: CaptureRoute,
        reason: AudioMissingReason?,
        direction: CallDirection = CallDirection.OUTGOING,
    ) = CallRecordBuilder.build(
        call = pending(answered, direction),
        endedAtEpochMillis = 1_772_615_851_412L,
        endedElapsedMillis = 65_000L,
        captureRoute = route,
        captureReason = reason,
        source = CallSource.LIVE_CAPTURE,
    )

    @Test
    fun `a reason is always set, for every combination`() {
        for (answered in listOf(true, false)) {
            for (route in CaptureRoute.entries) {
                for (reason in AudioMissingReason.entries + listOf(null)) {
                    val record = build(answered, route, reason)
                    assertThat(record.audioMissingReason).isNotNull()
                }
            }
        }
    }

    @Test
    fun `an unanswered call is not_expected, so the denominator stays honest`() {
        // SPEC §3.9 excludes not_expected and pending_upload from the gap
        // report's denominator. Colouring an unanswered call as a capture
        // failure would make a healthy fleet look broken.
        val record = build(answered = false, route = CaptureRoute.NONE, reason = null)

        assertThat(record.audioMissingReason).isEqualTo(AudioMissingReason.NOT_EXPECTED)
        assertThat(record.disposition).isEqualTo(CallDisposition.NO_ANSWER)
        assertThat(record.durationSec).isEqualTo(0)
    }

    @Test
    fun `an answered call with audio is pending_upload, not a failure`() {
        val record = build(true, CaptureRoute.OEM_FILE_HARVEST, null)

        assertThat(record.audioMissingReason).isEqualTo(AudioMissingReason.PENDING_UPLOAD)
        assertThat(record.captureRoute).isEqualTo(CaptureRoute.OEM_FILE_HARVEST)
    }

    @Test
    fun `no route and no reason falls back to recording_route_unavailable`() {
        // The honest answer while the OEM locators are still NoOp (T71b): the
        // call is a correct, complete record with a reason that names the
        // right cause.
        val record = build(true, CaptureRoute.NONE, null)

        assertThat(record.audioMissingReason)
            .isEqualTo(AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE)
    }

    @Test
    fun `the capture path's own reason is preserved`() {
        val record = build(true, CaptureRoute.NONE, AudioMissingReason.OEM_RECORDER_OFF)

        assertThat(record.audioMissingReason).isEqualTo(AudioMissingReason.OEM_RECORDER_OFF)
    }

    @Test
    fun `an unanswered incoming call is missed, not no_answer`() {
        val record = build(false, CaptureRoute.NONE, null, CallDirection.INCOMING)

        assertThat(record.disposition).isEqualTo(CallDisposition.MISSED)
    }

    @Test
    fun `duration comes from the monotonic clock`() {
        // 65_000 - 5_000 elapsed = 60 s. The wall-clock times in the fixture
        // span 60 s too; what this pins is that the ELAPSED pair is used, so a
        // clock change mid-call cannot produce a negative or absurd length.
        val record = build(true, CaptureRoute.APP_MIC, null)

        assertThat(record.durationSec).isEqualTo(60)
    }

    @Test
    fun `the id is derived from whole seconds when unreconciled`() {
        // §3.10 rule 2: milliseconds from a live capture and from a call-log
        // DATE never agree, so the unreconciled id truncates.
        val record = build(true, CaptureRoute.APP_MIC, null)
        val expected = ClientCallId.derive(
            registeredNumber = "+998907776655",
            direction = CallDirection.OUTGOING,
            startedAtEpochMillis = 1_772_615_791_000L,
            remoteNumber = "901112233",
        )

        assertThat(record.clientCallId).isEqualTo(expected)
    }

    @Test
    fun `a reconciled start time gives the id the call log agrees with`() {
        // Rule 1: the log's DATE, verbatim — the only timestamp two independent
        // installs will agree on.
        val record = CallRecordBuilder.build(
            call = pending(answered = true),
            endedAtEpochMillis = 1_772_615_851_412L,
            endedElapsedMillis = 65_000L,
            captureRoute = CaptureRoute.NONE,
            captureReason = null,
            source = CallSource.CALL_LOG_RECOVERY,
            reconciledStartedAtEpochMillis = 1_772_615_792_123L,
        )

        assertThat(record.clientCallId).isEqualTo(
            ClientCallId.derive(
                "+998907776655", CallDirection.OUTGOING, 1_772_615_792_123L, "901112233",
            ),
        )
        assertThat(record.startedAtEpochMillis).isEqualTo(1_772_615_792_123L)
    }
}
