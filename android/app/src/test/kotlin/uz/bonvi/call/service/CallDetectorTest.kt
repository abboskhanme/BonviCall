package uz.bonvi.call.service

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.Test
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallState
import uz.bonvi.call.domain.Decision
import uz.bonvi.call.domain.EnrolledSubscription
import uz.bonvi.call.domain.PrivacyBoundary
import uz.bonvi.call.domain.RejectReason
import uz.bonvi.call.domain.SubscriptionRule

/**
 * **The privacy boundary applies to DETECTION, not only to recording** (T69,
 * CONVENTIONS.md §8, SPEC §7.4).
 *
 * A call on an unregistered SIM must not enter the queue at all — not captured
 * and filtered server-side. These tests are the difference between a product
 * that respects the boundary and one that claims to, and they may not be
 * deleted, skipped or weakened.
 */
class CallDetectorTest {

    private val enrolled = EnrolledSubscription(
        subscriptionId = 2,
        registeredNumber = "+998901112233",
        isActive = true,
    )

    private class FakeSessionStore : CallSessionStore {
        private val rows = linkedMapOf<String, CallSessionManager.Session>()
        override suspend fun find(callId: String) = rows[callId]
        override suspend fun save(session: CallSessionManager.Session, updatedAtEpochMillis: Long) {
            rows[session.callId] = session
        }
        override suspend fun delete(callId: String) { rows.remove(callId) }
        override suspend fun all() = rows.values.toList()
    }

    private class FakePendingStore : PendingCallStore {
        val calls = linkedMapOf<String, PendingCall>()
        val discards = mutableListOf<RejectReason>()
        override suspend fun get(callId: String) = calls[callId]
        override suspend fun put(call: PendingCall) { calls[call.callId] = call }
        override suspend fun remove(callId: String) { calls.remove(callId) }
        override suspend fun all() = calls.values.toList()
        override suspend fun countDiscarded(reason: RejectReason) { discards += reason }
    }

    private fun detector(
        pending: FakePendingStore,
        sessions: CallSessionManager,
        enrolment: EnrolledSubscription = enrolled,
    ): CallDetector {
        val boundary = PrivacyBoundary { call -> SubscriptionRule.decide(call, enrolment) }
        return CallDetector(
            context = FakeContextStub.instance,
            boundary = boundary,
            sessions = sessions,
            pending = pending,
            onCallEnded = CallEndedListener { },
            io = kotlinx.coroutines.Dispatchers.Unconfined,
        )
    }

    @Test
    fun `a call on the registered SIM enters the pipeline`() = runTest {
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 2))

        assertThat(pending.calls).hasSize(1)
        assertThat(sessions.stateOf("c1")).isEqualTo(CallState.RINGING)
        assertThat(pending.calls.values.single().registeredNumber).isEqualTo("+998901112233")
    }

    @Test
    fun `a call on the employee's own SIM never enters the queue`() = runTest {
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 1))

        // NOTHING is stored: no number, no time, no queue row. The session
        // row is gone too — DISCARDED is terminal, so CallSessionManager
        // removes it, and the counter is the only trace the call leaves.
        assertThat(pending.calls).isEmpty()
        assertThat(sessions.activeCount()).isEqualTo(0)
        assertThat(pending.discards).containsExactly(RejectReason.NOT_REGISTERED_SUBSCRIPTION)
    }

    @Test
    fun `an unidentifiable subscription fails closed`() = runTest {
        // The branch somebody writes the wrong way round in a hurry: "we could
        // not tell, so assume it is the work SIM" uploads private calls.
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = null))

        assertThat(pending.calls).isEmpty()
        assertThat(pending.discards).containsExactly(RejectReason.SUBSCRIPTION_UNKNOWN)
    }

    @Test
    fun `a discarded call leaves a counter and nothing identifying`() = runTest {
        // A rejected call is one we have decided is not ours, so recording
        // which number it was would defeat the decision (N28).
        val pending = FakePendingStore()
        val detector = detector(pending, CallSessionManager(FakeSessionStore()))

        detector.handle(CallDetector.Edge.Ringing("c1", "907776655", subscriptionId = 1))

        assertThat(pending.discards).hasSize(1)
        assertThat(pending.all()).isEmpty()
    }

    @Test
    fun `nothing is captured before enrolment finishes`() = runTest {
        val pending = FakePendingStore()
        val detector = detector(
            pending,
            CallSessionManager(FakeSessionStore()),
            enrolment = enrolled.copy(subscriptionId = null),
        )

        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 2))

        assertThat(pending.calls).isEmpty()
        assertThat(pending.discards).containsExactly(RejectReason.NOT_ENROLLED)
    }

    @Test
    fun `a full call records an answer and an end`() = runTest {
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Dialing("c1", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.OffHook("c1"))
        detector.handle(CallDetector.Edge.Idle("c1"))

        val call = pending.calls.getValue("c1")
        assertThat(call.direction).isEqualTo(CallDirection.OUTGOING)
        assertThat(call.answeredAtEpochMillis).isNotNull()
        assertThat(call.endedAtEpochMillis).isNotNull()
        assertThat(sessions.stateOf("c1")).isEqualTo(CallState.ENDED)
    }

    @Test
    fun `a repeated ringing edge does not start a second call`() = runTest {
        // Some OEMs fire the same edge twice. Two rows for one call would be
        // two uploads with different ids.
        val pending = FakePendingStore()
        val detector = detector(pending, CallSessionManager(FakeSessionStore()))

        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 2))
        val first = pending.calls.getValue("c1")
        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 2))

        assertThat(pending.calls.getValue("c1")).isEqualTo(first)
    }

    @Test
    fun `an end for a call that was never started is ignored`() = runTest {
        // An idle edge arriving after a discarded call, which is the common
        // case: the boundary refused the ringing edge and the idle still comes.
        val pending = FakePendingStore()
        val detector = detector(pending, CallSessionManager(FakeSessionStore()))

        detector.handle(CallDetector.Edge.Idle("never-seen"))

        assertThat(pending.calls).isEmpty()
    }

    @Test
    fun `the capture proof carries the registered number, not the dialled one`() = runTest {
        val pending = FakePendingStore()
        val decision = SubscriptionRule.decide(
            uz.bonvi.call.domain.ObservedCall(
                subscriptionId = 2,
                phoneAccountId = null,
                direction = CallDirection.OUTGOING,
                startedAtEpochMillis = 1_000L,
                answeredAtEpochMillis = 2_000L,
                endedAtEpochMillis = 3_000L,
            ),
            enrolled,
        )

        assertThat(decision).isInstanceOf(Decision.Capture::class.java)
        assertThat((decision as Decision.Capture).registeredNumber).isEqualTo("+998901112233")
        assertThat(pending.calls).isEmpty()
    }
}
