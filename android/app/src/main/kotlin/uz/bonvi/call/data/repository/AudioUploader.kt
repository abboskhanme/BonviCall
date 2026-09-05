package uz.bonvi.call.data.repository

import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.remote.api.DeviceAudioApi
import uz.bonvi.call.data.remote.dto.AudioCodec
import uz.bonvi.call.data.remote.dto.AudioContainer
import uz.bonvi.call.data.remote.dto.CaptureRoute as CaptureRouteDto
import uz.bonvi.call.data.remote.dto.OpenUploadIn
import uz.bonvi.call.data.remote.toFailure
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.AudioFormat
import uz.bonvi.call.domain.AudioUploadPolicy
import uz.bonvi.call.domain.CaptureRoute
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.time.OffsetDateTime
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Uploads one recording, resumably (T74, SPEC §4.5).
 *
 * ═══ Resume is the point ═══════════════════════════════════════════════════
 * A twenty-minute recording over a weak cell connection will be interrupted.
 * Restarting from zero each time is the difference between arriving and never
 * arriving, so the first thing an upload does — every time, not only after a
 * crash — is ask the server how many bytes it already holds.
 *
 * ═══ N11: local audio is deleted only after the server confirms ════════════
 * The commit verifies the whole-file SHA-256 server-side. Until that returns,
 * the file stays on the phone. The one exception is a **permanent refusal**,
 * below.
 *
 * ═══ 409 `audio_not_attributable` is the privacy boundary at the far end ════
 * The server could not match the file to a registered-number call inside its
 * window, so it refused it and wrote no bytes. Retrying can never succeed —
 * the window does not reopen — and a client that retried would spend the
 * employee's data in a loop on a file the server has already decided is not the
 * company's. It is parked, reported, and **the local file is deleted**: keeping
 * a recording the server has refused is the one state worse than losing it.
 */
/**
 * The upload seam.
 *
 * An interface so `AudioPipeline`'s DELETION rules can be tested without a
 * network — and those are the rules that matter most here: an OEM-harvested
 * file must never be deleted, and a recording the server has refused must not
 * stay on the phone. Both are one-line mistakes and neither is visible in
 * production.
 */
interface AudioUpload {
    suspend fun upload(request: AudioUploader.Request): AudioUploader.Result
}

@Singleton
class AudioUploader @Inject constructor(
    private val api: DeviceAudioApi,
    private val moshi: Moshi,
    @IoDispatcher private val io: CoroutineDispatcher,
) : AudioUpload {

    data class Request(
        val clientCallId: String,
        val file: File,
        val target: AudioFormat.Target,
        val captureRoute: CaptureRoute,
        val captureRouteDetail: String?,
        val durationMs: Long,
        val recordedAtEpochMillis: Long,
    )

    sealed interface Result {
        /** Stored, checksum verified. The local file may now be deleted (N11). */
        data class Committed(val audioId: String, val bytes: Long) : Result

        /** Interrupted. The bytes the server has are kept; the next pass
         *  continues from there. */
        data class Interrupted(val uploadedBytes: Long) : Result

        /** Never going to succeed. Park it and report it; delete the local file
         *  when [deleteLocal] — the server has refused to hold it. */
        data class Refused(val code: String, val deleteLocal: Boolean) : Result
    }

    override suspend fun upload(request: Request): Result = withContext(io) {
        if (!request.file.isFile || request.file.length() == 0L) {
            return@withContext Result.Refused("local_file_missing", deleteLocal = false)
        }

        val sha256 = sha256Of(request.file)
        val session = api.openSession(request.clientCallId, request.file.openBody(request, sha256))
        val opened = session.body()
        if (!session.isSuccessful || opened == null) {
            val failure = session.toFailure(moshi)
            return@withContext if (AudioUploadPolicy.isPermanentFailure(failure.code)) {
                Timber.w("Audio refused permanently: %s", failure.code)
                Result.Refused(
                    failure.code,
                    AudioUploadPolicy.shouldDeleteLocalAudio(failure.code),
                )
            } else {
                Result.Interrupted(0)
            }
        }

        val uploadId = opened.uploadId.toString()
        // Resume from what the server already holds — every time, not only
        // after a crash. The session response carries it, so a fresh session
        // and a resumed one take the same path.
        var offset = opened.receivedBytes.toLong()
        val chunkSize = opened.chunkSize

        RandomAccessFile(request.file, "r").use { input ->
            val buffer = ByteArray(chunkSize)
            while (offset < request.file.length()) {
                input.seek(offset)
                val read = input.read(buffer)
                if (read <= 0) break

                val slice = buffer.copyOf(read)
                val response = api.putChunk(
                    uploadId = uploadId,
                    offset = offset,
                    // Per chunk, so a corrupted chunk is rejected now rather
                    // than at commit after the whole file has been sent.
                    chunkSha256 = sha256Of(slice),
                    body = slice.toRequestBody(OCTET_STREAM),
                )
                val accepted = response.body()
                if (!response.isSuccessful || accepted == null) {
                    val failure = response.toFailure(moshi)
                    if (AudioUploadPolicy.isPermanentFailure(failure.code)) {
                        return@withContext Result.Refused(
                            failure.code,
                            AudioUploadPolicy.shouldDeleteLocalAudio(failure.code),
                        )
                    }
                    // Includes chunk_offset_mismatch: the server knows the
                    // truth about what it holds, so the next pass re-reads it
                    // rather than arguing.
                    Timber.i("Chunk upload interrupted at %d (%s)", offset, failure.code)
                    return@withContext Result.Interrupted(offset)
                }
                offset = accepted.receivedBytes.toLong()
            }
        }

        val commit = api.commit(uploadId)
        val committed = commit.body()
        if (!commit.isSuccessful || committed == null) {
            val failure = commit.toFailure(moshi)
            return@withContext if (AudioUploadPolicy.isPermanentFailure(failure.code)) {
                Result.Refused(failure.code, AudioUploadPolicy.shouldDeleteLocalAudio(failure.code))
            } else {
                Result.Interrupted(offset)
            }
        }

        if (committed.sha256 != sha256) {
            // The server verified a different file from the one on the phone.
            // Not retryable as-is and not silently accepted either.
            Timber.e("Committed checksum does not match the local file")
            return@withContext Result.Refused("checksum_mismatch", deleteLocal = false)
        }

        Result.Committed(committed.audioId.toString(), committed.bytes.toLong())
    }

    private fun File.openBody(request: Request, sha256: String) = OpenUploadIn(
        //  carries format: int64 in the contract now, but the
        // generated type follows the schema — a single audio file is far
        // inside 32 bits either way (a 20-minute recording is ~3.6 MB).
        // The contract types this as a 32-bit integer, which is correct here:
        // a single recording is far inside it — a 20-minute call at N17's
        // 24 kbps is about 3.6 MB, and the chunk ceiling is 4 MiB.
        bytesTotal = length().toInt(),
        sha256 = sha256,
        codec = AudioCodec.entries.first { it.value == request.target.codec },
        container = AudioContainer.entries.first { it.value == request.target.container },
        captureRoute = CaptureRouteDto.entries.first { it.value == request.captureRoute.wire },
        captureRouteDetail = request.captureRouteDetail,
        recordedAt = OffsetDateTime.parse(Clock.toWire(request.recordedAtEpochMillis)),
        durationMs = request.durationMs.toInt(),
        sampleRateHz = AudioFormat.SAMPLE_RATE_HZ,
        channels = AudioFormat.CHANNELS,
        bitrateBps = AudioFormat.BITRATE_BPS,
    )

    private fun sha256Of(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { stream ->
            val buffer = ByteArray(DIGEST_BUFFER)
            while (true) {
                val read = stream.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().toHex()
    }

    private fun sha256Of(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).toHex()

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    private companion object {
        val OCTET_STREAM = "application/octet-stream".toMediaType()
        const val DIGEST_BUFFER = 64 * 1024
    }
}
