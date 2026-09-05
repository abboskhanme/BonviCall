package uz.bonvi.call.data.repository

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.local.PendingCallDao
import uz.bonvi.call.data.local.PendingCallEntity
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.RejectReason
import uz.bonvi.call.service.PendingCall
import uz.bonvi.call.service.PendingCallStore
import java.time.Instant
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import javax.inject.Singleton

/** The Room-backed [PendingCallStore]. Mapping only; every rule is in
 *  `CallDetector` and `CallStateMachine`. */
@Singleton
class RoomPendingCallStore @Inject constructor(
    private val dao: PendingCallDao,
    @IoDispatcher private val io: CoroutineDispatcher,
) : PendingCallStore {

    override suspend fun get(callId: String): PendingCall? = withContext(io) {
        dao.find(callId)?.toDomain()
    }

    override suspend fun put(call: PendingCall) = withContext(io) {
        dao.upsert(call.toEntity())
    }

    override suspend fun remove(callId: String) = withContext(io) { dao.delete(callId) }

    override suspend fun all(): List<PendingCall> = withContext(io) {
        dao.all().map { it.toDomain() }
    }

    /** Counted, never stored. See `DiscardCounterEntity`. */
    override suspend fun countDiscarded(reason: RejectReason) = withContext(io) {
        dao.incrementDiscard(today(), reason.wire)
    }

    /** The business day in Asia/Tashkent, which is what the gap report groups
     *  by — a fleet in one timezone should not have its counts split at UTC
     *  midnight, in the middle of the working afternoon. */
    private fun today(): String = DAY.format(
        Instant.ofEpochMilli(Clock.epochMillis()).atZone(Clock.TASHKENT),
    )

    private fun PendingCallEntity.toDomain() = PendingCall(
        callId = callId,
        direction = CallDirection.entries.first { it.wire == direction },
        remoteNumber = remoteNumber,
        registeredNumber = registeredNumber,
        subscriptionId = subscriptionId,
        startedAtEpochMillis = startedAtEpochMillis,
        startedElapsedMillis = startedElapsedMillis,
        answeredAtEpochMillis = answeredAtEpochMillis,
        endedAtEpochMillis = endedAtEpochMillis,
    )

    private fun PendingCall.toEntity() = PendingCallEntity(
        callId = callId,
        direction = direction.wire,
        remoteNumber = remoteNumber,
        registeredNumber = registeredNumber,
        subscriptionId = subscriptionId,
        startedAtEpochMillis = startedAtEpochMillis,
        startedElapsedMillis = startedElapsedMillis,
        answeredAtEpochMillis = answeredAtEpochMillis,
        endedAtEpochMillis = endedAtEpochMillis,
    )

    private companion object {
        val DAY: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    }
}
