package uz.bonvi.call.service

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import org.junit.Test
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallEvent
import uz.bonvi.call.domain.CallState
import uz.bonvi.call.domain.Decision
import uz.bonvi.call.domain.RejectReason

/**
 * Call sessions: one machine per call id, and it survives the process
 * (SPEC §7.5).
 *
 * The first of those is **R5**. Call waiting — a second call arriving during an
 * active one — is a separate call, and the prototype ignored it, so the second
 * call vanished. The second is what an aggressive OEM battery manager does to
 * the foreground service between a call ending and its audio being queued.
 */
class CallSessionManagerTest {

    /** In-memory [CallSessionStore]. The manager's rules are testable without
     *  Room precisely because the store is an interface. */
    private class FakeStore : CallSessionStore {
        private val rows = linkedMapOf<String, CallSessionManager.Session>()
        var writes = 0
            private set

        override suspend fun find(callId: String) = rows[callId]
        override suspend fun save(session: CallSessionManager.Session, updatedAtEpochMillis: Long) {
            writes++
            rows[session.callId] = session
        }
        override suspend fun delete(callId: String) { rows.remove(callId) }
        override suspend fun all() = rows.values.toList()

        /** Simulates a process death: the manager is gone, the rows are not. */
        fun survive(): FakeStore = this
    }

    private val proof = Decision.Capture(
        subscriptionId = 2,
        registeredNumber = "+998901112233",
        answeredAtEpochMillis = 1_000L,
        endedAtEpochMillis = 61_000L,
    )

    @Test
    fun `call waiting is a second machine, not an ignored event - R5`() = runTest {
        val store = FakeStore()
        val manager = CallSessionManager(store)

        // First call is active.
        manager.onEvent("call-1", CallEvent.Detected)
        manager.onEvent("call-1", CallEvent.Attributed(proof))
        manager.onEvent("call-1", CallEvent.Ringing(CallDirection.INCOMING))
        manager.onEvent("call-1", CallEvent.Answered)

        // A second call arrives while the first is talking.
        manager.onEvent("call-2", CallEvent.Detected)
        manager.onEvent("call-2", CallEvent.Attributed(proof))
        manager.onEvent("call-2", CallEvent.Ringing(CallDirection.INCOMING))

        assertThat(manager.stateOf("call-1")).isEqualTo(CallState.ACTIVE)
        assertThat(manager.stateOf("call-2")).isEqualTo(CallState.RINGING)
        assertThat(manager.activeCount()).isEqualTo(2)
    }

    @Test
    fun `each call ends independently`() = runTest {
        val manager = CallSessionManager(FakeStore())

        manager.onEvent("call-1", CallEvent.Detected)
        manager.onEvent("call-1", CallEvent.Answered)
        manager.onEvent("call-2", CallEvent.Detected)
        manager.onEvent("call-2", CallEvent.Answered)

        manager.onEvent("call-1", CallEvent.Hungup)

        assertThat(manager.stateOf("call-1")).isEqualTo(CallState.ENDED)
        assertThat(manager.stateOf("call-2")).isEqualTo(CallState.ACTIVE)
    }

    @Test
    fun `a session survives process death and resumes mid-call`() = runTest {
        val store = FakeStore()
        CallSessionManager(store).apply {
            onEvent("call-1", CallEvent.Detected)
            onEvent("call-1", CallEvent.Attributed(proof))
            onEvent("call-1", CallEvent.Answered)
            onEvent("call-1", CallEvent.Hungup)
            onEvent("call-1", CallEvent.ReconcileSucceeded)
        }

        // The service was killed here. A new manager over the same rows.
        val resumed = CallSessionManager(store.survive())

        val sessions = resumed.resume()
        assertThat(sessions.map { it.callId }).containsExactly("call-1")
        assertThat(sessions.single().state).isEqualTo(CallState.RECONCILING)

        // And it can be finished rather than restarted.
        resumed.onEvent("call-1", CallEvent.MetadataQueued)
        resumed.onEvent("call-1", CallEvent.AudioMissing(AudioMissingReason.APP_NOT_RUNNING))
        assertThat(resumed.onEvent("call-1", CallEvent.UploadConfirmed))
            .isEqualTo(CallState.COMPLETE)
    }

    @Test
    fun `every transition is written before it is acted on`() = runTest {
        val store = FakeStore()
        val manager = CallSessionManager(store)

        manager.onEvent("call-1", CallEvent.Detected)
        manager.onEvent("call-1", CallEvent.Answered)
        manager.onEvent("call-1", CallEvent.Hungup)

        // Three accepted transitions, three writes. Persisting only at the end
        // is what loses a call to a mid-call process death.
        assertThat(store.writes).isEqualTo(3)
    }

    @Test
    fun `an event the machine cannot accept is ignored, not thrown`() = runTest {
        val store = FakeStore()
        val manager = CallSessionManager(store)

        manager.onEvent("call-1", CallEvent.Detected)
        val writesBefore = store.writes

        // An OEM firing a hangup twice, or a log row closing a call already
        // closed. During a real call this is common; throwing would lose it.
        val state = manager.onEvent("call-1", CallEvent.UploadConfirmed)

        assertThat(state).isEqualTo(CallState.IDENTIFYING)
        assertThat(store.writes).isEqualTo(writesBefore)
    }

    @Test
    fun `a finished call leaves no session row`() = runTest {
        val store = FakeStore()
        val manager = CallSessionManager(store)

        manager.onEvent("call-1", CallEvent.Detected)
        manager.onEvent("call-1", CallEvent.Attributed(proof))
        manager.onEvent("call-1", CallEvent.Answered)
        manager.onEvent("call-1", CallEvent.Hungup)
        manager.onEvent("call-1", CallEvent.ReconcileSucceeded)
        manager.onEvent("call-1", CallEvent.MetadataQueued)
        manager.onEvent("call-1", CallEvent.AudioMissing(AudioMissingReason.NOT_EXPECTED))
        manager.onEvent("call-1", CallEvent.UploadConfirmed)

        // The record of the call lives in the upload queue, which is the queue
        // of record (N8). The session row only existed to survive a crash.
        assertThat(store.all()).isEmpty()
        assertThat(manager.activeCount()).isEqualTo(0)
    }

    @Test
    fun `a rejected call leaves no session row either`() = runTest {
        val store = FakeStore()
        val manager = CallSessionManager(store)

        manager.onEvent("call-1", CallEvent.Detected)
        manager.onEvent("call-1", CallEvent.Rejected(RejectReason.SUBSCRIPTION_UNKNOWN))

        // The privacy boundary said no, so nothing about this call persists.
        // A counter is the only trace it may leave.
        assertThat(store.all()).isEmpty()
    }
}
