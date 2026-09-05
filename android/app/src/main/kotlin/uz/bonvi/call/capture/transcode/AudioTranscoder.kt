package uz.bonvi.call.capture.transcode

import uz.bonvi.call.domain.AudioFormat
import uz.bonvi.call.domain.TranscodeFailure
import java.io.File

/**
 * Converts a raw recording into the upload format (T73, N17, SPEC §7.6).
 *
 * The seam exists for the same reason `RecordingStrategy` does: the encoder is
 * the part that behaves differently on every handset, and everything around it
 * — the queue, the reasons, the budgets — has to be testable without one.
 */
interface AudioTranscoder {

    sealed interface Result {
        data class Transcoded(
            val file: File,
            val target: AudioFormat.Target,
            val durationMs: Long,
            val bytes: Long,
        ) : Result

        /** The call still ships, with [TranscodeFailure.reason]. A transcode
         *  failure is never the reason a call is lost (UC-14). */
        data class Failed(val failure: TranscodeFailure, val detail: String?) : Result
    }

    /**
     * @param source the recorder's output. **Never modified or deleted here** —
     *        on the OEM harvest route it is the employee's own file
     *        (CONVENTIONS.md §8.3), and the caller owns the lifecycle of the
     *        app's own recordings.
     */
    suspend fun transcode(source: File, destinationDir: File): Result
}
