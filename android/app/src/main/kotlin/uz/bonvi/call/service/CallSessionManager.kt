package uz.bonvi.call.service

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.domain.CallEvent
import uz.bonvi.call.domain.CallState
import uz.bonvi.call.domain.CallStateMachine
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Where each in-flight call is, and it survives the process (SPEC §7.5).
 *
 * ═══ One machine per call id — this is R5 ══════════════════════════════════
 * A second RINGING during an active call is **call waiting**, and it is a
 * separate call. The prototype ignored it, the second call vanished, and that
 * is on the risk register. Keying by call id rather than holding a single
 * "current call" is the whole fix, and `CallSessionManagerTest` pins it.
 *
 * ═══ Persisted on every transition ═════════════════════════════════════════
 * The service is killed between a call ending and its audio being queued on any
 * handset with an aggressive battery manager — which is most of the fleet. Each
 * transition is written before it is acted on, so [resume] can finish a call
 * that was mid-reconciliation instead of losing it.
 *
 * The store is an interface so the rule is testable without a database; the
 * Room DAO implements it.
 */
@Singleton
class CallSessionManager @Inject constructor(
    private val store: CallSessionStore,
) {

    /** One in-flight call. */
    data class Session(
        val callId: String,
        val state: CallState,
        val clientCallId: String?,
    )

    // Transitions arrive from the telephony callback thread and from workers.
    // A mutex rather than synchronised: everything here suspends.
    private val lock = Mutex()

    /**
     * Apply [event] to [callId]'s machine, creating it if this is the first
     * time we have seen the call.
     *
     * Returns the state after the transition. An event the machine cannot
     * accept leaves the state alone and is LOGGED — during a real call an
     * unexpected event is common (an OEM firing the active edge twice, a hangup
     * arriving after the log already closed the call), and throwing would lose
     * a call that is otherwise fine.
     */
    suspend fun onEvent(callId: String, event: CallEvent): CallState = lock.withLock {
        val current = store.find(callId)?.state ?: CallStateMachine.INITIAL
        val result = CallStateMachine.next(current, event)

        result.illegal?.let {
            Timber.w("Ignored %s in state %s for call %s", event::class.simpleName, it.from, callId)
            return@withLock current
        }

        val clientCallId = (event as? CallEvent.Attributed)?.let { store.find(callId)?.clientCallId }
        store.save(
            Session(callId = callId, state = result.state, clientCallId = clientCallId),
            updatedAtEpochMillis = Clock.epochMillis(),
        )

        if (result.state.isTerminal) {
            // The row's job is to survive process death mid-call. A finished
            // call has nothing left to resume, and the record of it lives in
            // the upload queue, which is the queue of record (N8).
            store.delete(callId)
        }
        result.state
    }

    /** Attach the idempotency key once the call is attributed. */
    suspend fun bindClientCallId(callId: String, clientCallId: String) = lock.withLock {
        val existing = store.find(callId) ?: return@withLock
        store.save(existing.copy(clientCallId = clientCallId), Clock.epochMillis())
    }

    suspend fun stateOf(callId: String): CallState =
        store.find(callId)?.state ?: CallStateMachine.INITIAL

    /** Every call still in flight. Called on service start. */
    suspend fun resume(): List<Session> = lock.withLock {
        val sessions = store.all().filterNot { it.state.isTerminal }
        if (sessions.isNotEmpty()) {
            Timber.i("Resuming %d call session(s) after a restart", sessions.size)
        }
        sessions
    }

    /** How many calls are in flight. A number above one is call waiting, not a
     *  bug — see R5 above. */
    suspend fun activeCount(): Int = store.all().count { !it.state.isTerminal }
}

/**
 * Storage for [CallSessionManager]. An interface so the manager's rules — the
 * per-call-id keying and the resume pass — are unit-tested without Room, which
 * is the difference between those rules having tests and not having them.
 */
interface CallSessionStore {
    suspend fun find(callId: String): CallSessionManager.Session?
    suspend fun save(session: CallSessionManager.Session, updatedAtEpochMillis: Long)
    suspend fun delete(callId: String)
    suspend fun all(): List<CallSessionManager.Session>
}
