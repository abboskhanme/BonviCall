package uz.bonvi.call.service

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.data.repository.AudioJobRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Sends the recordings whose calls have landed (T73, T74, N11).
 *
 * ═══ Why audio waits for metadata ══════════════════════════════════════════
 * The server accepts audio only against a call it already holds, so a recording
 * cannot be uploaded when the call ends — `client_call_id` does not exist until
 * the sweep derives it from the call log twenty seconds later, and the call
 * itself has to reach the server before its audio does. This runs after the
 * metadata drain for exactly that reason: by then the call is either confirmed
 * or still queued, and a job whose call has not arrived is simply left for the
 * next pass.
 *
 * ═══ What it never does ════════════════════════════════════════════════════
 * It does not decide what to delete. `AudioPipeline` owns that, and the rule it
 * enforces is the one that matters most on a phone the employee owns: an
 * OEM-harvested file is never deleted, and a recording the server has
 * permanently refused never stays.
 */
@Singleton
class AudioDrain @Inject constructor(
    private val jobs: AudioJobRepository,
    private val pipeline: AudioPipeline,
    private val capture: CallCapture,
    private val session: SessionStore,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    /** [unfinished] is the only one worth coming back for: it means bytes are
     *  on the server and more are on the phone. A recording that will never be
     *  sent is not a retry, it is a call that shipped with a reason. */
    data class Outcome(val uploaded: Int, val unfinished: Int, val waiting: Int)

    suspend fun drainOnce(): Outcome = withContext(io) {
        // The same rule the metadata queue follows (N25): a device that cannot
        // send HOLDS its recordings. Nothing is ever deleted here to make room.
        if (!session.authStateSnapshot().canSend) return@withContext Outcome(0, 0, 0)

        var uploaded = 0
        var unfinished = 0
        for (job in jobs.next()) {
            if (!job.file.isFile) {
                // The file is gone — deleted by a cleaner, or by revocation
                // (UC-08). The call is already on the server with its own
                // reason; carrying a job that can never succeed would retry
                // forever.
                Timber.w("Audio for %s is no longer on disk", job.clientCallId)
                jobs.done(job.clientCallId)
                continue
            }

            when (
                val outcome = pipeline.process(
                    clientCallId = job.clientCallId,
                    recording = job.file,
                    captureRoute = job.captureRoute,
                    recordedAtEpochMillis = job.recordedAtEpochMillis,
                    workDir = capture.workDir(),
                )
            ) {
                is AudioPipeline.Outcome.Uploaded -> {
                    jobs.done(job.clientCallId)
                    uploaded++
                }

                // Network, or a partial upload to resume. The row stays and the
                // server already holds the bytes that got through.
                is AudioPipeline.Outcome.Retry -> {
                    jobs.failed(job.clientCallId, "interrupted")
                    unfinished++
                }

                // A transcode that cannot work, or a refusal that will not
                // change. The call keeps the honest reason it already shipped
                // with; retrying would spend the employee's data on a file the
                // server has decided is not the company's.
                is AudioPipeline.Outcome.NoAudio -> {
                    Timber.i(
                        "No audio for %s: %s",
                        job.clientCallId, outcome.reason.wire,
                    )
                    jobs.done(job.clientCallId)
                }
            }
        }

        val waiting = jobs.depth()
        if (uploaded > 0 || unfinished > 0) {
            Timber.i(
                "Audio pass: %d uploaded, %d unfinished, %d waiting",
                uploaded, unfinished, waiting,
            )
        }
        Outcome(uploaded, unfinished, waiting)
    }

}
