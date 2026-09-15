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
        capture: CallCapture = FakeCapture(),
    ): CallDetector {
        val boundary = PrivacyBoundary { call -> SubscriptionRule.decide(call, enrolment) }
        return CallDetector(
            context = FakeContextStub.instance,
            boundary = boundary,
            sessions = sessions,
            pending = pending,
            onCallEnded = CallEndedListener { },
            capture = capture,
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


    // ── The recorder is asked, and only for calls that are ours ───────────

    @Test
    fun `an answered work call is recorded, and the proof travels with it`() = runTest {
        val pending = FakePendingStore()
        val capture = FakeCapture()
        val detector = detector(pending, CallSessionManager(FakeSessionStore()), capture = capture)

        detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.OffHook("c1"))

        // `prepare` carries the Decision.Capture, which is the only thing a
        // router can be built from — so a recording is impossible for a call
        // that did not pass Guard 1.
        assertThat(capture.prepared).containsExactly("c1")
        assertThat(capture.started).containsExactly("c1")
    }

    @Test
    fun `a private call is never prepared for capture`() = runTest {
        val pending = FakePendingStore()
        val capture = FakeCapture()
        val detector = detector(pending, CallSessionManager(FakeSessionStore()), capture = capture)

        // The employee's own SIM. Nothing about this call may reach the
        // recorder — not a start that is later discarded, nothing at all.
        detector.handle(CallDetector.Edge.Ringing("c9", "901112233", subscriptionId = 7))
        detector.handle(CallDetector.Edge.OffHook("c9"))

        assertThat(capture.prepared).isEmpty()
        assertThat(capture.started).isEmpty()
    }

    @Test
    fun `an unanswered call never starts the recorder`() = runTest {
        val pending = FakePendingStore()
        val capture = FakeCapture()
        val detector = detector(pending, CallSessionManager(FakeSessionStore()), capture = capture)

        detector.handle(CallDetector.Edge.Ringing("c2", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.Idle("c2"))

        // A missed call has no conversation to record. Starting a recorder
        // against a ringtone would also take the microphone from the dialler.
        assertThat(capture.started).isEmpty()
        assertThat(capture.stopped).containsExactly("c2")
    }

    @Test
    fun `what capture produced is written on the call, not held in memory`() = runTest {
        val pending = FakePendingStore()
        val file = java.io.File("build/tmp/c3.m4a")
        val capture = FakeCapture(
            outcome = CaptureOutcome(
                file = file,
                route = uz.bonvi.call.domain.CaptureRoute.APP_VOICE_RECOGNITION,
                reason = null,
            ),
        )
        val detector = detector(pending, CallSessionManager(FakeSessionStore()), capture = capture)

        detector.handle(CallDetector.Edge.Ringing("c3", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.OffHook("c3"))
        detector.handle(CallDetector.Edge.Idle("c3"))

        // The sweep reads this twenty seconds later, and the service is killed
        // between those two moments on most of this fleet. In memory it would
        // be a recording of a call that happened, lost.
        val row = pending.calls.getValue("c3")
        assertThat(row.audioPath).isEqualTo(file.path)
        assertThat(row.captureRoute)
            .isEqualTo(uz.bonvi.call.domain.CaptureRoute.APP_VOICE_RECOGNITION)
        assertThat(row.audioReason).isNull()
    }

    @Test
    fun `a call that produced no audio carries the reason instead`() = runTest {
        val pending = FakePendingStore()
        val capture = FakeCapture(
            outcome = CaptureOutcome(
                file = null,
                route = uz.bonvi.call.domain.CaptureRoute.NONE,
                reason = uz.bonvi.call.domain.AudioMissingReason.CAPTURE_RETURNED_SILENCE,
            ),
        )
        val detector = detector(pending, CallSessionManager(FakeSessionStore()), capture = capture)

        detector.handle(CallDetector.Edge.Ringing("c4", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.OffHook("c4"))
        detector.handle(CallDetector.Edge.Idle("c4"))

        // N5: never free text, and never absent. A call with no audio and no
        // reason inflates the gap report against a phone that is working.
        val row = pending.calls.getValue("c4")
        assertThat(row.audioPath).isNull()
        assertThat(row.audioReason)
            .isEqualTo(uz.bonvi.call.domain.AudioMissingReason.CAPTURE_RETURNED_SILENCE)
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

    // --- Outgoing calls, found live on 2026-09-11 ---------------------------
    //
    // The platform reports an outgoing call as IDLE → OFFHOOK → IDLE: there is
    // no RINGING. `Edge.Dialing` was written for this and produced by nothing,
    // so `Edge.OffHook` found no session and returned — **every outgoing call
    // was invisible to live capture** and arrived hours later from the
    // call-log sweep marked `app_not_running`, which reads as a dead app
    // rather than a missing branch. Measured on a Xiaomi 13 Lite: three
    // outgoing test calls, three sweep recoveries, no live session.

    @Test
    fun `an OFFHOOK with no session open is an outgoing call`() = runTest {
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(
            CallDetector.Edge.OffHook("c1", remoteNumber = "901112233", subscriptionId = 2),
        )

        assertThat(pending.calls).hasSize(1)
        assertThat(pending.calls.values.single().direction).isEqualTo(CallDirection.OUTGOING)
        // Answered, because OFFHOOK is the moment an outgoing call connects.
        assertThat(pending.calls.values.single().answeredAtEpochMillis).isNotNull()
    }

    @Test
    fun `an OFFHOOK on a private SIM is still refused`() {
        // The fix must not become a way past Guard 1. An outgoing call on the
        // employee's own SIM is theirs, and opening a session from OFFHOOK
        // must obey the boundary exactly as RINGING does.
        runTest {
            val pending = FakePendingStore()
            val capture = FakeCapture()
            val detector = detector(pending, CallSessionManager(FakeSessionStore()), capture = capture)

            detector.handle(
                CallDetector.Edge.OffHook("c1", remoteNumber = "901112233", subscriptionId = 7),
            )

            assertThat(pending.calls).isEmpty()
            assertThat(capture.started).isEmpty()
        }
    }

    @Test
    fun `an OFFHOOK with an unknown SIM is refused, not guessed`() {
        // The live TelephonyCallback reports only a state. Before the source
        // was scoped to the enrolled subscription every edge arrived with a
        // null id — and a boundary that guessed here would upload private
        // calls, so it fails closed instead.
        runTest {
            val pending = FakePendingStore()
            val detector = detector(pending, CallSessionManager(FakeSessionStore()))

            detector.handle(CallDetector.Edge.OffHook("c1", subscriptionId = null))

            assertThat(pending.calls).isEmpty()
        }
    }

    @Test
    fun `two calls in a row do not share a session or an audio file`() {
        // ⚠️ The live source used a CONSTANT call id, so every call collided
        // with the last. The capture file is named from the id, so the second
        // call overwrote the first's recording — and the first, already
        // queued, shipped `recording_route_unavailable` while a good recording
        // of the wrong conversation sat on disk. Measured on a Xiaomi 13 Lite,
        // 2026-09-11.
        runTest {
            val pending = FakePendingStore()
            val sessions = CallSessionManager(FakeSessionStore())
            val detector = detector(pending, sessions)

            detector.handle(CallDetector.Edge.OffHook("live-100", subscriptionId = 2))
            detector.handle(CallDetector.Edge.Idle("live-100"))
            detector.handle(CallDetector.Edge.OffHook("live-200", subscriptionId = 2))

            // TWO rows, not one overwritten. A finished call keeps its row
            // until the sweep reconciles it, so the guarantee that matters is
            // that the second call never lands on top of the first.
            assertThat(pending.calls).hasSize(2)
            assertThat(pending.calls.keys).containsExactly("live-100", "live-200")
            // And the first is finished — its own ending, not the second's.
            assertThat(pending.calls.getValue("live-100").endedAtEpochMillis).isNotNull()
            assertThat(pending.calls.getValue("live-200").endedAtEpochMillis).isNull()
        }
    }

    @Test
    fun `an OFFHOOK after a RINGING keeps the incoming call it belongs to`() {
        // The fix must not turn an answered INCOMING call into an outgoing
        // one: the session already exists, so OFFHOOK only answers it.
        runTest {
            val pending = FakePendingStore()
            val sessions = CallSessionManager(FakeSessionStore())
            val detector = detector(pending, sessions)

            detector.handle(CallDetector.Edge.Ringing("c1", "901112233", subscriptionId = 2))
            detector.handle(CallDetector.Edge.OffHook("c1", subscriptionId = 2))

            assertThat(pending.calls).hasSize(1)
            assertThat(pending.calls.values.single().direction).isEqualTo(CallDirection.INCOMING)
        }
    }

    @Test
    fun `the other source reporting the same in-flight call does not open a second call`() = runTest {
        // The live callback and the manifest receiver both see every call and
        // name it differently. Both attributed the CEO's 16:27 call (2026-09-12):
        // two sessions, two recorders, two harvests of one file.
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.OffHook("live-1", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.OffHook("sub-2", "901112233", subscriptionId = 2))

        assertThat(pending.calls.keys).containsExactly("live-1")
        assertThat(sessions.stateOf("sub-2")).isEqualTo(CallState.IDLE)
    }

    @Test
    fun `a second incoming call during an active one is still a second call`() = runTest {
        // Call waiting (R5). The same-SIM rule must not swallow it: the first
        // call is ANSWERED when the second one rings, and one SIM cannot be
        // ringing twice, so this RINGING edge is a new call.
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Ringing("live-1", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.OffHook("live-1", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.Ringing("live-2", "909998877", subscriptionId = 2))

        assertThat(pending.calls.keys).containsExactly("live-1", "live-2")
        assertThat(sessions.stateOf("live-2")).isEqualTo(CallState.RINGING)
    }

    @Test
    fun `the receiver's copy of a ringing call is not a second call`() = runTest {
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Ringing("live-1", "901112233", subscriptionId = 2))
        detector.handle(CallDetector.Edge.Ringing("sub-2", "901112233", subscriptionId = 2))

        assertThat(pending.calls.keys).containsExactly("live-1")
    }

    @Test
    fun `a stale in-flight row does not shadow the next call on the SIM`() = runTest {
        val pending = FakePendingStore()
        val sessions = CallSessionManager(FakeSessionStore())
        val detector = detector(pending, sessions)
        pending.put(
            PendingCall(
                callId = "lost-end",
                direction = CallDirection.OUTGOING,
                remoteNumber = "901112233",
                registeredNumber = "+998901112233",
                subscriptionId = 2,
                // Four hours ago: its end edge was lost with the process.
                startedAtEpochMillis = uz.bonvi.call.core.Clock.epochMillis() - 4 * 60 * 60 * 1000L,
                startedElapsedMillis = 0L,
                answeredAtEpochMillis = null,
            ),
        )

        detector.handle(CallDetector.Edge.OffHook("live-2", "901112233", subscriptionId = 2))

        assertThat(pending.calls.keys).containsExactly("lost-end", "live-2")
    }
}

/**
 * Capture, without a phone.
 *
 * The detector's job here is the privacy boundary: a rejected call must never
 * reach [prepare], and an answered one must. Recording it for real needs an
 * Android runtime; recording THAT it was asked for is what these tests check.
 */
private class FakeCapture(private val outcome: CaptureOutcome? = null) : CallCapture {
    val prepared = mutableListOf<String>()
    val started = mutableListOf<String>()
    val stopped = mutableListOf<String>()

    override fun prepare(callId: String, capture: uz.bonvi.call.domain.Decision.Capture) {
        prepared += callId
    }

    override fun start(callId: String) { started += callId }

    override fun stop(callId: String): CaptureOutcome? {
        stopped += callId
        return outcome
    }

    override fun discard(callId: String) = Unit
    override fun releaseAll() = Unit
    override fun isCapturing(): Boolean = false
    override fun workDir(): java.io.File = java.io.File("build/tmp")
}
