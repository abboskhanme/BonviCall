package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.BeforeClass
import org.junit.Test
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallEvent
import uz.bonvi.call.domain.CallState
import uz.bonvi.call.domain.Decision
import uz.bonvi.call.domain.EnrolledSubscription
import uz.bonvi.call.domain.PrivacyBoundary
import uz.bonvi.call.domain.RejectReason
import uz.bonvi.call.domain.SubscriptionRule
import uz.bonvi.call.service.CallDetector
import uz.bonvi.call.service.CallEndedListener
import uz.bonvi.call.service.CallSessionManager
import uz.bonvi.call.service.CallSessionStore
import uz.bonvi.call.service.PendingCall
import uz.bonvi.call.service.PendingCallStore
import uz.bonvi.call.service.FakeContextStub

/**
 * Process death at every point, and two calls at once.
 *
 * A phone with an aggressive OEM battery manager is killed constantly, and the
 * client's handsets are exactly those. Every state the machine can be left in
 * has to be resumable — a call stranded mid-flight is a call that never
 * existed.
 */
class LiveRestartTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()
    }

    private class Store : CallSessionStore {
        val rows = linkedMapOf<String, CallSessionManager.Session>()
        override suspend fun find(callId: String) = rows[callId]
        override suspend fun save(session: CallSessionManager.Session, updatedAtEpochMillis: Long) {
            rows[session.callId] = session
        }
        override suspend fun delete(callId: String) { rows.remove(callId) }
        override suspend fun all() = rows.values.toList()
    }

    private class Pending : PendingCallStore {
        val calls = linkedMapOf<String, PendingCall>()
        val discards = mutableListOf<RejectReason>()
        override suspend fun get(callId: String) = calls[callId]
        override suspend fun put(call: PendingCall) { calls[call.callId] = call }
        override suspend fun remove(callId: String) { calls.remove(callId) }
        override suspend fun all() = calls.values.toList()
        override suspend fun countDiscarded(reason: RejectReason) { discards += reason }
    }

    private val enrolled = EnrolledSubscription(2, "+998901112233", isActive = true)

    private fun detector(pending: Pending, sessions: CallSessionManager) = CallDetector(
        context = FakeContextStub.instance,
        boundary = PrivacyBoundary { SubscriptionRule.decide(it, enrolled) },
        sessions = sessions,
        pending = pending,
        onCallEnded = CallEndedListener { },
        capture = NoCapture,
        io = kotlinx.coroutines.Dispatchers.Unconfined,
    )

    /**
     * WALL 26: killed at every state in turn. Each one must resume to exactly
     * where it was, because the alternative is a call that vanishes.
     */
    @Test
    fun `every in-flight state survives a restart`() = runTest {
        val states = listOf(
            listOf(CallEvent.Detected) to CallState.IDENTIFYING,
            listOf(CallEvent.Detected, CallEvent.Ringing(CallDirection.INCOMING)) to CallState.RINGING,
            listOf(CallEvent.Detected, CallEvent.Answered) to CallState.ACTIVE,
            listOf(CallEvent.Detected, CallEvent.Answered, CallEvent.Hungup) to CallState.ENDED,
            listOf(
                CallEvent.Detected, CallEvent.Answered, CallEvent.Hungup,
                CallEvent.ReconcileSucceeded,
            ) to CallState.RECONCILING,
        )

        for ((events, expected) in states) {
            val store = Store()
            CallSessionManager(store).apply { events.forEach { onEvent("c", it) } }

            // The process dies here. A new manager over the same rows.
            val resumed = CallSessionManager(store)
            assertThat(resumed.stateOf("c")).isEqualTo(expected)
            assertThat(resumed.resume().single().state).isEqualTo(expected)
        }
    }

    /**
     * WALL 27: **R5** — a second call arriving during an active one is call
     * waiting, and it is a separate call. The prototype ignored it and the
     * second call vanished.
     */
    @Test
    fun `a second call during an active one is a second call, not a lost one`() = runTest {
        val store = Store()
        val pending = Pending()
        val sessions = CallSessionManager(store)
        val detector = detector(pending, sessions)

        detector.handle(CallDetector.Edge.Ringing("call-1", "901112233", 2))
        detector.handle(CallDetector.Edge.OffHook("call-1"))
        detector.handle(CallDetector.Edge.Ringing("call-2", "907776655", 2))

        assertThat(sessions.stateOf("call-1")).isEqualTo(CallState.ACTIVE)
        assertThat(sessions.stateOf("call-2")).isEqualTo(CallState.RINGING)
        assertThat(sessions.activeCount()).isEqualTo(2)
        assertThat(pending.all()).hasSize(2)

        // And both survive a restart independently.
        val resumed = CallSessionManager(store)
        assertThat(resumed.resume().map { it.callId }).containsExactly("call-1", "call-2")
    }

    /**
     * WALL 28: a call killed mid-flight on the OTHER SIM leaves nothing behind
     * — the privacy boundary holds across a restart, not just within one.
     */
    @Test
    fun `a rejected call leaves nothing for a restart to resume`() = runTest {
        val store = Store()
        val pending = Pending()
        val detector = detector(pending, CallSessionManager(store))

        detector.handle(CallDetector.Edge.Ringing("call-1", "901112233", subscriptionId = 1))

        val resumed = CallSessionManager(store)
        assertThat(resumed.resume()).isEmpty()
        assertThat(pending.all()).isEmpty()
        assertThat(pending.discards).containsExactly(RejectReason.NOT_REGISTERED_SUBSCRIPTION)
    }

    /**
     * WALL 29: an unidentifiable SIM, killed mid-call. Still nothing. The
     * fail-closed decision must not become fail-open on the resume path.
     */
    @Test
    fun `an unknown subscription leaves nothing, restart or not`() = runTest {
        val store = Store()
        val pending = Pending()
        val detector = detector(pending, CallSessionManager(store))

        detector.handle(CallDetector.Edge.Ringing("call-1", "901112233", subscriptionId = null))
        detector.handle(CallDetector.Edge.Idle("call-1"))

        assertThat(CallSessionManager(store).resume()).isEmpty()
        assertThat(pending.all()).isEmpty()
        assertThat(pending.discards).containsExactly(RejectReason.SUBSCRIPTION_UNKNOWN)
    }

    /**
     * WALL 30: the proof a capture depends on survives being rebuilt from a
     * resumed row — otherwise a resumed call could reach the locator without
     * one.
     */
    @Test
    fun `a resumed call still needs the capture proof`() = runTest {
        val decision = SubscriptionRule.decide(
            uz.bonvi.call.domain.ObservedCall(
                subscriptionId = 2, phoneAccountId = null,
                direction = CallDirection.OUTGOING,
                startedAtEpochMillis = 1_000, answeredAtEpochMillis = 2_000,
                endedAtEpochMillis = 3_000,
            ),
            enrolled,
        )
        assertThat(decision).isInstanceOf(Decision.Capture::class.java)
        // And the same observation on a different SIM never yields one, however
        // it was reconstructed.
        assertThat(
            SubscriptionRule.decide(
                uz.bonvi.call.domain.ObservedCall(
                    subscriptionId = 1, phoneAccountId = null,
                    direction = CallDirection.OUTGOING,
                    startedAtEpochMillis = 1_000, answeredAtEpochMillis = 2_000,
                    endedAtEpochMillis = 3_000,
                ),
                enrolled,
            ),
        ).isInstanceOf(Decision.Reject::class.java)
    }
}

/** The capture path is an Android runtime; this suite is about what survives a
 *  restart, which is the database. */
private object NoCapture : uz.bonvi.call.service.CallCapture {
    override fun prepare(callId: String, capture: uz.bonvi.call.domain.Decision.Capture) = Unit
    override fun start(callId: String) = Unit
    override fun stop(callId: String): uz.bonvi.call.service.CaptureOutcome? = null
    override fun discard(callId: String) = Unit
    override fun releaseAll() = Unit
    override fun isCapturing(): Boolean = false
    override fun workDir(): java.io.File = java.io.File("build/tmp")
}
