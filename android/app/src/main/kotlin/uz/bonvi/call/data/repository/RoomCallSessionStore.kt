package uz.bonvi.call.data.repository

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import uz.bonvi.call.data.local.CallSessionDao
import uz.bonvi.call.data.local.CallSessionEntity
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.service.CallSessionManager
import uz.bonvi.call.service.CallSessionStore
import javax.inject.Inject
import javax.inject.Singleton

/** The Room-backed [CallSessionStore]. Mapping only — every rule is in
 *  `CallSessionManager` and every transition is in `CallStateMachine`. */
@Singleton
class RoomCallSessionStore @Inject constructor(
    private val dao: CallSessionDao,
    @IoDispatcher private val io: CoroutineDispatcher,
) : CallSessionStore {

    override suspend fun find(callId: String): CallSessionManager.Session? = withContext(io) {
        dao.find(callId)?.toSession()
    }

    override suspend fun save(
        session: CallSessionManager.Session,
        updatedAtEpochMillis: Long,
    ) = withContext(io) {
        dao.upsert(
            CallSessionEntity(
                callId = session.callId,
                state = session.state,
                clientCallId = session.clientCallId,
                updatedAtEpochMillis = updatedAtEpochMillis,
            ),
        )
    }

    override suspend fun delete(callId: String) = withContext(io) { dao.delete(callId) }

    override suspend fun all(): List<CallSessionManager.Session> = withContext(io) {
        dao.all().map { it.toSession() }
    }

    private fun CallSessionEntity.toSession() = CallSessionManager.Session(
        callId = callId,
        state = state,
        clientCallId = clientCallId,
    )
}
