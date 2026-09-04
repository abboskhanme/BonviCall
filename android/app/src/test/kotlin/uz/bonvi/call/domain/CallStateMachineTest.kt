package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The call lifecycle (SPEC §7.5).
 *
 * The machine is persisted on every transition so a process death resumes
 * rather than restarts, which is why the transition rule is pure and tested
 * here rather than only exercised through the foreground service.
 */
class CallStateMachineTest {

    private val proof = Decision.Capture(
        subscriptionId = 2,
        registeredNumber = "+998901112233",
        answeredAtEpochMillis = 1_000L,
        endedAtEpochMillis = 61_000L,
    )

    private fun run(vararg events: CallEvent): CallState =
        events.fold(CallStateMachine.INITIAL) { state, event ->
            CallStateMachine.next(state, event).state
        }

    @Test
    fun `an answered outgoing call runs to COMPLETE with audio`() {
        val state = run(
            CallEvent.Detected,
            CallEvent.Attributed(proof),
            CallEvent.Ringing(CallDirection.OUTGOING),
            CallEvent.Answered,
            CallEvent.Hungup,
            CallEvent.ReconcileSucceeded,
            CallEvent.MetadataQueued,
            CallEvent.AudioCaptured,
            CallEvent.AudioQueued,
            CallEvent.UploadConfirmed,
        )

        assertThat(state).isEqualTo(CallState.COMPLETE)
    }

    @Test
    fun `an unanswered outgoing call still reaches COMPLETE`() {
        // UC-09: it is never reported as a conversation, and it is never
        // dropped either. The row exists with no answer time and zero duration.
        val state = run(
            CallEvent.Detected,
            CallEvent.Attributed(proof),
            CallEvent.Ringing(CallDirection.OUTGOING),
            CallEvent.Hungup,
            CallEvent.ReconcileSucceeded,
            CallEvent.MetadataQueued,
            CallEvent.AudioMissing(AudioMissingReason.NOT_EXPECTED),
            CallEvent.UploadConfirmed,
        )

        assertThat(state).isEqualTo(CallState.COMPLETE)
    }

    @Test
    fun `a call the boundary rejects is DISCARDED before anything is written`() {
        val result = CallStateMachine.next(
            CallState.IDENTIFYING,
            CallEvent.Rejected(RejectReason.SUBSCRIPTION_UNKNOWN),
        )

        assertThat(result.state).isEqualTo(CallState.DISCARDED)
        assertThat(result.state.isTerminal).isTrue()
        // Terminal means terminal: no later event resurrects it into a queued
        // call. The counter is the only trace an unregistered call leaves.
        assertThat(CallStateMachine.next(CallState.DISCARDED, CallEvent.MetadataQueued).state)
            .isEqualTo(CallState.DISCARDED)
        assertThat(CallStateMachine.next(CallState.DISCARDED, CallEvent.AudioCaptured).changed)
            .isFalse()
    }

    @Test
    fun `a call is never dropped because audio failed`() {
        // UC-14. Every AudioMissing path still ends at COMPLETE, which is what
        // "the call is uploaded anyway, with a reason" means in the machine.
        for (reason in AudioMissingReason.entries) {
            val state = run(
                CallEvent.Detected,
                CallEvent.Attributed(proof),
                CallEvent.Ringing(CallDirection.INCOMING),
                CallEvent.Answered,
                CallEvent.Hungup,
                CallEvent.ReconcileSucceeded,
                CallEvent.MetadataQueued,
                CallEvent.AudioMissing(reason),
                CallEvent.UploadConfirmed,
            )
            assertThat(state).isEqualTo(CallState.COMPLETE)
        }
    }

    @Test
    fun `audio that vanishes after capture degrades to NO_AUDIO rather than sticking`() {
        // The file was there at stop() and gone at upload: deleted by a cleaner
        // app, or the queue filled. It must not strand the call in AUDIO_PENDING
        // forever, because a stranded call is one the panel never sees.
        val state = run(
            CallEvent.Detected,
            CallEvent.Attributed(proof),
            CallEvent.Answered,
            CallEvent.Hungup,
            CallEvent.ReconcileSucceeded,
            CallEvent.MetadataQueued,
            CallEvent.AudioCaptured,
            CallEvent.AudioMissing(AudioMissingReason.QUEUE_SPACE_EXHAUSTED),
        )

        assertThat(state).isEqualTo(CallState.NO_AUDIO)
    }

    @Test
    fun `a call log that never produces a row still queues the metadata`() {
        // SPEC §7.5's sweep reports the gap rather than inventing a row.
        val state = run(
            CallEvent.Detected,
            CallEvent.Attributed(proof),
            CallEvent.Answered,
            CallEvent.Hungup,
            CallEvent.ReconcileGaveUp,
            CallEvent.MetadataQueued,
            CallEvent.AudioMissing(AudioMissingReason.NOT_EXPECTED),
            CallEvent.UploadConfirmed,
        )

        assertThat(state).isEqualTo(CallState.COMPLETE)
    }

    @Test
    fun `an OEM that repeats ACTIVE does not derail the call`() {
        // Some handsets fire the active edge more than once. An impossible
        // event during a real call must not throw: it would take down the
        // capture of a call that is otherwise fine.
        val result = CallStateMachine.next(CallState.ACTIVE, CallEvent.Answered)

        assertThat(result.state).isEqualTo(CallState.ACTIVE)
        assertThat(result.changed).isTrue()
    }

    @Test
    fun `an impossible event is reported as data, not thrown`() {
        val result = CallStateMachine.next(CallState.IDLE, CallEvent.UploadConfirmed)

        assertThat(result.state).isEqualTo(CallState.IDLE)
        assertThat(result.illegal).isEqualTo(
            IllegalTransition(CallState.IDLE, CallEvent.UploadConfirmed),
        )
    }

    @Test
    fun `an incoming call that is never answered is a missed call, not a discard`() {
        val state = run(
            CallEvent.Detected,
            CallEvent.Attributed(proof),
            CallEvent.Ringing(CallDirection.INCOMING),
            CallEvent.Hungup,
        )

        assertThat(state).isEqualTo(CallState.ENDED)
    }

    @Test
    fun `direction decides RINGING versus DIALING`() {
        assertThat(
            CallStateMachine.next(
                CallState.IDENTIFYING,
                CallEvent.Ringing(CallDirection.INCOMING),
            ).state,
        ).isEqualTo(CallState.RINGING)

        assertThat(
            CallStateMachine.next(
                CallState.IDENTIFYING,
                CallEvent.Ringing(CallDirection.OUTGOING),
            ).state,
        ).isEqualTo(CallState.DIALING)
    }

    @Test
    fun `every state is reachable from IDLE`() {
        // A state nobody can reach is a state nobody maintains. Breadth-first
        // over the whole event alphabet.
        val events = listOf(
            CallEvent.Detected,
            CallEvent.Attributed(proof),
            CallEvent.Rejected(RejectReason.SUBSCRIPTION_UNKNOWN),
            CallEvent.Ringing(CallDirection.INCOMING),
            CallEvent.Ringing(CallDirection.OUTGOING),
            CallEvent.Answered,
            CallEvent.Hungup,
            CallEvent.ReconcileSucceeded,
            CallEvent.ReconcileGaveUp,
            CallEvent.MetadataQueued,
            CallEvent.AudioCaptured,
            CallEvent.AudioMissing(AudioMissingReason.NO_PERMISSION),
            CallEvent.AudioQueued,
            CallEvent.UploadConfirmed,
        )
        val reached = mutableSetOf(CallStateMachine.INITIAL)
        val frontier = ArrayDeque(reached)
        while (frontier.isNotEmpty()) {
            val state = frontier.removeFirst()
            for (event in events) {
                val next = CallStateMachine.next(state, event).state
                if (reached.add(next)) frontier.addLast(next)
            }
        }

        assertThat(reached).containsExactlyElementsIn(CallState.entries)
    }
}
