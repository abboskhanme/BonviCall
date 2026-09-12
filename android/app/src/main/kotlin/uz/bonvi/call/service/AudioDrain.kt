package uz.bonvi.call.service

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
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

    /**
     * One pass at a time, process-wide.
     *
     * The one-shot and the periodic `CallUploadWorker` are separate unique
     * works, so WorkManager will happily run both at once — and both then
     * take the same jobs, transcode the same source into the SAME work file,
     * and one of them hashes a file the other is still rewriting. Measured
     * the moment the transcoder stopped hanging (2026-09-12): two upload
     * sessions for one call a second apart, the first refused
     * `checksum_mismatch`. A refusal with that code discards the job, so the
     * race does not merely waste data; it can lose a recording.
     */
    private val onePassAtATime = Mutex()

    suspend fun drainOnce(): Outcome = onePassAtATime.withLock { drainLocked() }

    private suspend fun drainLocked(): Outcome = withContext(io) {
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

                // The server has no call to hang this recording on. Coming
                // back sooner cannot help — the call's own metadata has to
                // land first, and it is the metadata drain, not this one, that
                // decides when. So it is NOT counted as unfinished (which
                // would make the worker retry with backoff), and it is
                // bounded: a call the server has refused for good — an
                // unanswered outgoing call sent as `answered`, before that
                // was fixed — held one job in 409 on every pass, the worker in
                // exponential backoff, and every later recording behind it
                // (2026-09-12). After enough passes the recording is given up
                // with a reason; an OEM file is never deleted, ours is.
                is AudioPipeline.Outcome.Retry -> if (outcome.code == CALL_NOT_FOUND) {
                    jobs.failed(job.clientCallId, outcome.code)
                    if (job.attempts + 1 >= MAX_PASSES_WITHOUT_CALL) {
                        Timber.w(
                            "Audio for %s: the server never received its call in %d passes; giving up",
                            job.clientCallId, MAX_PASSES_WITHOUT_CALL,
                        )
                        if (job.captureRoute != uz.bonvi.call.domain.CaptureRoute.OEM_FILE_HARVEST) {
                            job.file.delete()
                        }
                        jobs.done(job.clientCallId)
                    }
                } else {
                    // Network, or a partial upload to resume. The row stays
                    // and the server already holds the bytes that got through.
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

    private companion object {
        const val CALL_NOT_FOUND = "call_not_found"

        /** Twelve passes — three hours at the periodic cadence — is long past
         *  any metadata parking policy; a call still absent by then is one the
         *  server has refused for good. */
        const val MAX_PASSES_WITHOUT_CALL = 12
    }
}
