package uz.bonvi.call.data.repository

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.local.QueuedCallDao
import uz.bonvi.call.data.local.QueuedCallEntity
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.UploadPolicy
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The durable upload queue, N8's "queue of record".
 *
 * It applies `UploadPolicy` to the DAO. The policy is pure and tested on its
 * own; this class is the part that needs a database, and it is deliberately
 * thin so there is little here that a test could not reach.
 *
 * Everything runs on the injected IO dispatcher — nothing in this class may be
 * called from the main thread (CONVENTIONS-CLIENT.md §8), and injecting the
 * dispatcher rather than naming `Dispatchers.IO` is what lets a test drive it.
 */
@Singleton
class CallQueueRepository @Inject constructor(
    private val dao: QueuedCallDao,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** Queue depth as the heartbeat reports it (SPEC §5.2: records AND bytes). */
    data class Depth(val pending: Int, val parked: Int, val bytes: Long)

    /**
     * Add a call to the queue.
     *
     * Idempotent by the schema: a duplicate `clientCallId` is ignored, so the
     * recovery sweep (UC-13) can re-offer a call the live path already queued
     * without creating a second row or resetting its attempt count.
     *
     * @return true when a new row was created.
     */
    suspend fun enqueue(clientCallId: String, payloadJson: String): Boolean = withContext(io) {
        val inserted = dao.enqueue(
            QueuedCallEntity(
                clientCallId = clientCallId,
                payloadJson = payloadJson,
                queuedAtEpochMillis = Clock.epochMillis(),
            ),
        )
        val created = inserted != -1L
        if (!created) Timber.d("Call already queued; not re-queued")
        created
    }

    /** The next rows to send: oldest first, parked excluded, backoff respected. */
    suspend fun nextBatch(limit: Int = DEFAULT_BATCH): List<QueuedCallEntity> = withContext(io) {
        dao.nextBatch(nowEpochMillis = Clock.epochMillis(), limit = limit)
    }

    /**
     * Record a failed send and decide what happens next.
     *
     * @param status the HTTP status, or 0 when nothing reached a server.
     * @param code the error envelope's code, or null.
     */
    suspend fun recordFailure(
        row: QueuedCallEntity,
        status: Int,
        code: String?,
    ): UploadPolicy.Outcome = withContext(io) {
        when (val outcome = UploadPolicy.onFailure(row.attempts, status, code)) {
            is UploadPolicy.Outcome.Retry -> {
                dao.recordAttempt(
                    clientCallId = row.clientCallId,
                    errorCode = code,
                    nextAttemptAtEpochMillis = Clock.epochMillis() + outcome.afterSeconds * 1_000L,
                )
                outcome
            }

            is UploadPolicy.Outcome.Park -> {
                // The row STAYS. It is reported on the next heartbeat, and the
                // panel shows it as a parked record. Deleting it here would
                // make the failure invisible, and an invisible failure in this
                // product is a call that never existed.
                dao.park(
                    clientCallId = row.clientCallId,
                    parkedAtEpochMillis = Clock.epochMillis(),
                    errorCode = outcome.reason,
                )
                Timber.w("Call parked after %d attempts: %s", row.attempts + 1, outcome.reason)
                outcome
            }

            is UploadPolicy.Outcome.Confirmed -> outcome
        }
    }

    /**
     * The server has the row. Only now is it deleted (N11: local audio is
     * removed only after the server confirms the checksum, and the metadata row
     * follows the same rule).
     */
    suspend fun confirm(clientCallId: String) = withContext(io) {
        dao.deleteConfirmed(clientCallId)
    }

    suspend fun depth(): Depth = withContext(io) {
        Depth(
            pending = dao.pendingCount(),
            parked = dao.parkedCount(),
            bytes = dao.queuedBytes(),
        )
    }

    companion object {
        /** SPEC §4.0's payload limit is 50 items or 256 KiB per batch. */
        const val DEFAULT_BATCH = 50
    }
}
