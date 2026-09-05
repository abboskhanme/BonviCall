package uz.bonvi.call.service

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.capture.transcode.AudioTranscoder
import uz.bonvi.call.data.repository.AudioUpload
import uz.bonvi.call.data.repository.AudioUploader
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Recording → transcode → upload → delete (T73, T74, N11).
 *
 * The order and the deletion points are the whole content of this class:
 *
 *  • **Transcode before upload** (N17), so the cellular bill and the storage
 *    bill are the same ~10.8 MB/hour number rather than five times it.
 *  • **A transcode failure never loses the call** (UC-14): the call ships with
 *    an honest `audio_missing_reason` from the closed enum.
 *  • **Local audio is deleted only after the server confirms the SHA-256**
 *    (N11) — or when the server has permanently refused it, because a
 *    recording the server will not hold must not sit on the employee's phone
 *    forever either.
 *
 * The app's own recordings are ours to delete. An **OEM-harvested file never
 * is**: it belongs to the employee and is opened read-only, never moved,
 * modified or deleted (CONVENTIONS.md §8.3). [deleteSourceIfOurs] is where that
 * distinction lives, and it is why the capture route travels this far.
 */
@Singleton
class AudioPipeline @Inject constructor(
    private val transcoder: AudioTranscoder,
    private val uploader: AudioUpload,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    sealed interface Outcome {
        data class Uploaded(val audioId: String, val bytes: Long) : Outcome

        /** Try again later — network, or a partial upload to resume. */
        data class Retry(val uploadedBytes: Long) : Outcome

        /** The call ships with this reason and the audio is not retried. */
        data class NoAudio(val reason: AudioMissingReason, val detail: String?) : Outcome
    }

    suspend fun process(
        clientCallId: String,
        recording: File,
        captureRoute: CaptureRoute,
        recordedAtEpochMillis: Long,
        workDir: File,
    ): Outcome = withContext(io) {
        val transcoded = when (val result = transcoder.transcode(recording, workDir)) {
            is AudioTranscoder.Result.Failed -> {
                // The call still ships. This is UC-14 in one line.
                Timber.w("Transcode failed (%s); the call ships without audio", result.failure)
                deleteSourceIfOurs(recording, captureRoute)
                return@withContext Outcome.NoAudio(result.failure.reason, result.detail)
            }

            is AudioTranscoder.Result.Transcoded -> result
        }

        val result = uploader.upload(
            AudioUploader.Request(
                clientCallId = clientCallId,
                file = transcoded.file,
                target = transcoded.target,
                captureRoute = captureRoute,
                captureRouteDetail = null,
                durationMs = transcoded.durationMs,
                recordedAtEpochMillis = recordedAtEpochMillis,
            ),
        )

        when (result) {
            is AudioUploader.Result.Committed -> {
                // N11: only now. The server has verified the checksum.
                transcoded.file.delete()
                deleteSourceIfOurs(recording, captureRoute)
                Outcome.Uploaded(result.audioId, result.bytes)
            }

            is AudioUploader.Result.Interrupted -> Outcome.Retry(result.uploadedBytes)

            is AudioUploader.Result.Refused -> {
                if (result.deleteLocal) {
                    // The server refused to hold it — most often
                    // `audio_not_attributable`, which is the privacy boundary
                    // at the far end. Keeping a recording the server has
                    // decided is not the company's is worse than losing it.
                    transcoded.file.delete()
                    deleteSourceIfOurs(recording, captureRoute)
                }
                Outcome.NoAudio(reasonFor(result.code), result.code)
            }
        }
    }

    /**
     * Delete the recorder's output — **but only when it is ours**.
     *
     * An OEM-harvested file is the employee's own recording, in their own
     * folder. It is opened read-only and never moved, modified or deleted
     * (CONVENTIONS.md §8.3); deleting one would be a worse breach than never
     * having captured it.
     */
    private fun deleteSourceIfOurs(recording: File, captureRoute: CaptureRoute) {
        if (captureRoute == CaptureRoute.OEM_FILE_HARVEST) return
        recording.delete()
    }

    private fun reasonFor(code: String): AudioMissingReason = when (code) {
        "audio_not_attributable" -> AudioMissingReason.ATTRIBUTION_FAILED
        "audio_expired", "upload_expired" -> AudioMissingReason.UPLOAD_EXPIRED
        "checksum_mismatch" -> AudioMissingReason.CAPTURE_RETURNED_SILENCE
        else -> AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE
    }
}
