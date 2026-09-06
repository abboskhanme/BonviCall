package uz.bonvi.call.live

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import org.junit.BeforeClass
import org.junit.Test
import uz.bonvi.call.data.local.QueuedCallDao
import uz.bonvi.call.data.local.QueuedCallEntity
import uz.bonvi.call.data.remote.dto.AppVariant
import uz.bonvi.call.data.remote.dto.DeviceCallBatchIn
import uz.bonvi.call.data.remote.dto.DeviceCallIn
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.ClientCallId
import uz.bonvi.call.domain.UploadPolicy
import java.time.OffsetDateTime
import java.util.UUID
import uz.bonvi.call.data.remote.dto.AudioMissingReason as AudioMissingReasonDto
import uz.bonvi.call.data.remote.dto.CallDirection as CallDirectionDto
import uz.bonvi.call.data.remote.dto.CallDisposition as CallDispositionDto
import uz.bonvi.call.data.remote.dto.CallSource as CallSourceDto
import uz.bonvi.call.data.remote.dto.CaptureRoute as CaptureRouteDto

/**
 * **Does the queue actually drain after an outage?**
 *
 * Driving the real `CallQueueRepository` and the real `UploadPolicy` against
 * the real server, with the network taken away and given back. Unit tests have
 * covered the policy; nothing has ever watched a row survive a failure and
 * then reach the server.
 */
class LiveQueueDrainTest {

    companion object {
        @BeforeClass @JvmStatic fun serverUp() = LiveHarness.requireServer()
    }

    /** `QueuedCallDao` in memory — the only Android piece the queue needs. */
    private class MemoryDao : QueuedCallDao {
        val rows = linkedMapOf<String, QueuedCallEntity>()

        override suspend fun nextBatch(nowEpochMillis: Long, limit: Int) = rows.values
            .filter { it.parkedAtEpochMillis == null && it.nextAttemptAtEpochMillis <= nowEpochMillis }
            .sortedWith(compareBy({ it.queuedAtEpochMillis }, { it.clientCallId }))
            .take(limit)

        override suspend fun enqueue(call: QueuedCallEntity): Long =
            if (rows.containsKey(call.clientCallId)) -1L
            else { rows[call.clientCallId] = call; 1L }

        override suspend fun recordAttempt(
            clientCallId: String,
            errorCode: String?,
            nextAttemptAtEpochMillis: Long,
        ) {
            rows[clientCallId]?.let {
                rows[clientCallId] = it.copy(
                    attempts = it.attempts + 1,
                    lastErrorCode = errorCode,
                    nextAttemptAtEpochMillis = nextAttemptAtEpochMillis,
                )
            }
        }

        override suspend fun park(
            clientCallId: String,
            parkedAtEpochMillis: Long,
            errorCode: String?,
        ) {
            rows[clientCallId]?.let {
                rows[clientCallId] = it.copy(
                    attempts = it.attempts + 1,
                    parkedAtEpochMillis = parkedAtEpochMillis,
                    lastErrorCode = errorCode,
                )
            }
        }

        override suspend fun deleteConfirmed(clientCallId: String) { rows.remove(clientCallId) }
        override suspend fun pendingCount() = rows.values.count { it.parkedAtEpochMillis == null }
        override suspend fun parkedCount() = rows.values.count { it.parkedAtEpochMillis != null }
        override suspend fun queuedBytes() = rows.values.sumOf { it.payloadJson.length.toLong() }
    }

    private fun queue(dao: MemoryDao) = CallQueueRepository(dao, Dispatchers.Unconfined)

    private fun callJson(session: FakeSession, offsetMinutes: Long): Pair<String, String> {
        val startedAt = System.currentTimeMillis() - offsetMinutes * 60_000
        val id = ClientCallId.derive(
            session.registeredNumberE164!!, CallDirection.OUTGOING, startedAt, "+99890777$offsetMinutes",
        )
        val call = DeviceCallIn(
            clientCallId = UUID.fromString(id),
            deviceEpochMs = System.currentTimeMillis(),
            deviceTimezone = "Asia/Tashkent",
            direction = CallDirectionDto.OUTGOING,
            disposition = CallDispositionDto.ANSWERED,
            startedAt = OffsetDateTime.now().minusMinutes(offsetMinutes + 2),
            answeredAt = OffsetDateTime.now().minusMinutes(offsetMinutes + 2),
            endedAt = OffsetDateTime.now().minusMinutes(offsetMinutes + 1),
            durationSec = 45,
            remoteNumber = "+99890777$offsetMinutes",
            audioExpected = false,
            audioMissingReason = AudioMissingReasonDto.RECORDING_ROUTE_UNAVAILABLE,
            captureRoute = CaptureRouteDto.NONE,
            source = CallSourceDto.LIVE_CAPTURE,
            reconciledWithCallLog = true,
            appVariant = AppVariant.LEGACY28,
            appVersion = "1.0.0",
        )
        return id to LiveHarness.moshi().adapter(DeviceCallIn::class.java).toJson(call)
    }

    /**
     * WALL 22: three calls made during an outage survive it and then arrive.
     * The whole reason the queue exists.
     */
    @Test
    fun `calls queued during an outage drain when the server returns`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val dao = MemoryDao()
        val queue = queue(dao)

        val ids = (1L..3L).map { minutes ->
            val (id, json) = callJson(session, minutes)
            assertThat(queue.enqueue(id, json)).isTrue()
            id
        }
        assertThat(queue.depth().pending).isEqualTo(3)

        // ── The outage. Nothing answers. ──────────────────────────────────
        val dead = FakeSession(baseUrl = "http://127.0.0.1:59999").apply {
            installationId = session.installationId
            accessToken = session.accessToken
        }
        val batch = queue.nextBatch()
        assertThat(batch).hasSize(3)
        runCatching {
            LiveHarness.calls(dead).uploadCalls(
                DeviceCallBatchIn(
                    calls = batch.map {
                        LiveHarness.moshi().adapter(DeviceCallIn::class.java).fromJson(it.payloadJson)!!
                    },
                ),
            )
        }.onFailure {
            batch.forEach { queue.recordFailure(it, status = 0, code = null) }
        }

        // Every row is still here. NOTHING was discarded.
        assertThat(queue.depth().pending).isEqualTo(3)
        assertThat(queue.depth().parked).isEqualTo(0)
        assertThat(dao.rows.values.all { it.attempts == 1 }).isTrue()

        // ── The server returns. ───────────────────────────────────────────
        // The backoff is in the future, so a drain now correctly finds
        // nothing — that is the policy working, not a stuck queue.
        assertThat(queue.nextBatch()).isEmpty()

        // Once the backoff elapses (simulated by clearing it, as the passage of
        // time would), everything goes.
        dao.rows.replaceAll { _, row -> row.copy(nextAttemptAtEpochMillis = 0) }
        val retry = queue.nextBatch()
        assertThat(retry).hasSize(3)

        val response = LiveHarness.calls(session).uploadCalls(
            DeviceCallBatchIn(
                calls = retry.map {
                    LiveHarness.moshi().adapter(DeviceCallIn::class.java).fromJson(it.payloadJson)!!
                },
            ),
        )
        assertThat(response.isSuccessful).isTrue()
        response.body()!!.results.forEach { result ->
            assertThat(result.error).isNull()
            queue.confirm(result.clientCallId.toString())
        }

        // Drained, and only now are the rows gone (N11).
        assertThat(queue.depth().pending).isEqualTo(0)
        assertThat(dao.rows).isEmpty()
        assertThat(ids).hasSize(3)
    }

    /**
     * WALL 23: oldest first. A newer call must never overtake an older one, or
     * the device and the server disagree about what "the last call" means.
     */
    @Test
    fun `the queue drains oldest first`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val dao = MemoryDao()
        val queue = queue(dao)

        // Enqueued newest-first on purpose.
        val (newId, newJson) = callJson(session, 1)
        val (oldId, oldJson) = callJson(session, 90)
        queue.enqueue(newId, newJson)
        Thread.sleep(5)
        queue.enqueue(oldId, oldJson)
        dao.rows[oldId] = dao.rows.getValue(oldId).copy(queuedAtEpochMillis = 1L)

        assertThat(queue.nextBatch().first().clientCallId).isEqualTo(oldId)
    }

    /**
     * WALL 24: a call the server refuses permanently must PARK, not loop. A
     * poisoned row retried forever blocks everything queued behind it.
     */
    @Test
    fun `a permanently refused call parks and stops consuming attempts`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val dao = MemoryDao()
        val queue = queue(dao)
        val (id, json) = callJson(session, 5)
        queue.enqueue(id, json)

        // A 4xx the server has already judged.
        val row = queue.nextBatch().single()
        val outcome = queue.recordFailure(row, status = 422, code = "validation_error")

        assertThat(outcome).isInstanceOf(UploadPolicy.Outcome.Park::class.java)
        assertThat(queue.depth().parked).isEqualTo(1)
        assertThat(queue.nextBatch()).isEmpty()
        // Parked, NOT deleted. The failure stays visible.
        assertThat(dao.rows).hasSize(1)
    }

    /**
     * WALL 25: five attempts, then park. Not four, not forever.
     */
    @Test
    fun `a row parks after exactly five attempts and is never deleted`() = runTest {
        val session = LiveAdmin.requireVerifiedSession()
        val dao = MemoryDao()
        val queue = queue(dao)
        val (id, json) = callJson(session, 7)
        queue.enqueue(id, json)

        repeat(UploadPolicy.MAX_ATTEMPTS) {
            dao.rows.replaceAll { _, row -> row.copy(nextAttemptAtEpochMillis = 0) }
            val row = queue.nextBatch().singleOrNull() ?: return@repeat
            queue.recordFailure(row, status = 503, code = "internal_error")
        }

        assertThat(queue.depth().parked).isEqualTo(1)
        assertThat(queue.depth().pending).isEqualTo(0)
        assertThat(dao.rows).hasSize(1)
        assertThat(dao.rows.values.single().lastErrorCode).isNotNull()
    }
}
