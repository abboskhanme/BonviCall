package uz.bonvi.call.data.repository

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.local.AudioJobDao
import uz.bonvi.call.data.local.AudioJobEntity
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.CaptureRoute
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The recordings waiting for their call to be confirmed (T73, T74).
 *
 * A row is written when the sweep queues the call's metadata — which is the
 * first moment `client_call_id` exists — and deleted when the audio has been
 * stored, refused, or has no file left to send. Nothing here decides anything;
 * `AudioPipeline` owns the transcode, the upload and the deletion rules.
 */
@Singleton
class AudioJobRepository @Inject constructor(
    private val dao: AudioJobDao,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    data class Job(
        val clientCallId: String,
        val file: File,
        val captureRoute: CaptureRoute,
        val recordedAtEpochMillis: Long,
        val attempts: Int,
    )

    /** Idempotent by `client_call_id`: the sweep may see the same call twice,
     *  and one call has one recording. */
    suspend fun enqueue(
        clientCallId: String,
        path: String,
        captureRoute: CaptureRoute,
        recordedAtEpochMillis: Long,
    ) = withContext(io) {
        dao.upsert(
            AudioJobEntity(
                clientCallId = clientCallId,
                path = path,
                captureRoute = captureRoute.wire,
                recordedAtEpochMillis = recordedAtEpochMillis,
                queuedAtEpochMillis = Clock.epochMillis(),
            ),
        )
    }

    suspend fun next(limit: Int = DEFAULT_BATCH): List<Job> = withContext(io) {
        dao.next(limit).map { row ->
            Job(
                clientCallId = row.clientCallId,
                file = File(row.path),
                // An unknown route resolves to NONE, which makes the file
                // ours-to-delete rule fail SAFE: an OEM file is never deleted,
                // so a row we cannot read is treated as one we may not touch.
                captureRoute = CaptureRoute.entries.firstOrNull { it.wire == row.captureRoute }
                    ?: CaptureRoute.OEM_FILE_HARVEST,
                recordedAtEpochMillis = row.recordedAtEpochMillis,
                attempts = row.attempts,
            )
        }
    }

    suspend fun done(clientCallId: String) = withContext(io) { dao.delete(clientCallId) }

    suspend fun failed(clientCallId: String, code: String?) = withContext(io) {
        dao.recordAttempt(clientCallId, code)
    }

    suspend fun depth(): Int = withContext(io) { dao.count() }

    private companion object {
        /** One at a time would be safer for memory and slower for a phone with
         *  a day of backlog; three is the compromise the upload worker runs at
         *  every fifteen minutes anyway. */
        const val DEFAULT_BATCH = 3
    }
}
