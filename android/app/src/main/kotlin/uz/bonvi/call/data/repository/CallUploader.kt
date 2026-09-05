package uz.bonvi.call.data.repository

import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.data.remote.api.DeviceCallsApi
import uz.bonvi.call.data.remote.dto.DeviceCallBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCallIn
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.AuthStateRule
import uz.bonvi.call.domain.DeviceAuthState
import uz.bonvi.call.domain.UploadPolicy
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Drains the queue (T74's client half).
 *
 * ═══ At-least-once delivery, exactly-once storage ══════════════════════════
 * `POST /calls` is a batch upsert keyed on `client_call_id`, so this class
 * never has to know whether a previous attempt got through. A reply lost on the
 * way back costs one retry, not one duplicate (N2: duplicate rate must be 0).
 *
 * A row is deleted **only** after the server has acknowledged it by id (N11).
 * A partial batch is normal — the server answers per call — and every id it did
 * not accept keeps its row and its attempt count.
 */
@Singleton
class CallUploader @Inject constructor(
    private val api: DeviceCallsApi,
    private val queue: CallQueueRepository,
    private val session: SessionStore,
    private val moshi: Moshi,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    data class Outcome(val sent: Int, val confirmed: Int, val parked: Int, val retryLater: Boolean)

    suspend fun drainOnce(): Outcome = withContext(io) {
        // T79/N25 and T83/N34, in one check.
        //
        // `UPDATE_REQUIRED` deliberately still sends: the server accepts a
        // stale client's queued records and refuses it only once the backlog is
        // empty, so a client that stopped sending would strand exactly the data
        // the gate was designed to protect. `AUTH_EXPIRED` and `REVOKED` stop
        // sending and **hold** the queue — nothing is ever discarded here.
        val authState = session.authStateSnapshot()
        if (!authState.canSend) {
            Timber.i("Not sending: device is %s. The queue is held.", authState.wire)
            return@withContext Outcome(0, 0, 0, retryLater = false)
        }

        val batch = queue.nextBatch()
        if (batch.isEmpty()) return@withContext Outcome(0, 0, 0, retryLater = false)

        val adapter = moshi.adapter(DeviceCallIn::class.java)
        val calls = batch.mapNotNull { row ->
            @Suppress("TooGenericExceptionCaught")
            try {
                adapter.fromJson(row.payloadJson)
            } catch (error: Exception) {
                // A row whose payload cannot be parsed can never succeed, so
                // retrying it forever would block the queue behind it. Park it:
                // it stays, it is reported, and a human sees it.
                Timber.e(error, "Queued payload could not be parsed; parking it")
                queue.recordFailure(row, status = 0, code = "payload_unreadable")
                null
            }
        }
        if (calls.isEmpty()) return@withContext Outcome(0, 0, batch.size, retryLater = false)

        val response = @Suppress("TooGenericExceptionCaught") try {
            api.uploadCalls(DeviceCallBatchIn(calls = calls))
        } catch (error: Exception) {
            // No response at all — a phone in a lift, which is the normal case
            // this queue exists for. Every row keeps its place and its order.
            Timber.i("Upload could not reach the server; %d call(s) stay queued", batch.size)
            batch.forEach { queue.recordFailure(it, status = 0, code = null) }
            return@withContext Outcome(batch.size, 0, 0, retryLater = true)
        }

        val body = response.body()
        if (!response.isSuccessful || body == null) {
            val failure = response.toFailure(moshi)
            // N34's refusal, or a revoke. Recorded so the UI can say why; the
            // queue is untouched either way.
            val nextState = AuthStateRule.next(authState, failure.status, failure.code)
            if (nextState != authState) session.saveAuthState(nextState.wire)
            var parked = 0
            batch.forEach { row ->
                val outcome = queue.recordFailure(row, failure.status, failure.code)
                if (outcome is UploadPolicy.Outcome.Park) parked++
            }
            return@withContext Outcome(
                sent = batch.size,
                confirmed = 0,
                parked = parked,
                retryLater = failure.isRetryable,
            )
        }

        // Per-call results: the server accepts a batch PARTIALLY, and a call
        // it rejected must keep its row rather than vanish with the batch.
        // `error` on a result is what says which.
        val byId = body.results.associateBy { it.clientCallId.toString() }
        var confirmed = 0
        var parked = 0
        for (row in batch) {
            val result = byId[row.clientCallId]
            when {
                result == null -> {
                    // The server did not mention this call at all. Neither
                    // accepted nor rejected, so it stays queued — dropping it
                    // would lose a call on a server bug.
                    queue.recordFailure(row, status = response.code(), code = "no_result_returned")
                }

                result.error == null -> {
                    // `unchanged` and `updated` are both success: a replay and
                    // a first write are indistinguishable by design (§3.10.4).
                    queue.confirm(row.clientCallId)
                    confirmed++
                }

                else -> {
                    val outcome = queue.recordFailure(
                        row,
                        status = response.code(),
                        code = result.error.code,
                    )
                    if (outcome is UploadPolicy.Outcome.Park) parked++
                }
            }
        }

        Outcome(
            sent = batch.size,
            confirmed = confirmed,
            parked = parked,
            // More may be waiting: the batch is capped at 50 (SPEC §4.0).
            retryLater = confirmed == batch.size && batch.size >= CallQueueRepository.DEFAULT_BATCH,
        )
    }
}
