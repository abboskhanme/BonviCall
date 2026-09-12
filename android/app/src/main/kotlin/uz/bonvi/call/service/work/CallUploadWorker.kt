package uz.bonvi.call.service.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import timber.log.Timber
import uz.bonvi.call.data.repository.CallUploader
import uz.bonvi.call.service.AudioDrain
import uz.bonvi.call.service.Revocation
import java.util.concurrent.TimeUnit

/**
 * Drains the queue, and survives the process doing it (T74, N8).
 *
 * `WorkManager` rather than a coroutine on the service's scope, for the reason
 * CONVENTIONS-CLIENT.md §8 gives: **anything that must survive process death**
 * goes here. The service is killed between a call ending and its upload on any
 * handset with an aggressive battery manager, and that is exactly the moment
 * the record is most valuable and least durable.
 *
 * `Result.retry()` rather than `failure()` on a transient problem — a failed
 * worker is never rerun, and the row it was carrying would sit in the queue
 * until something else happened to schedule a drain.
 */
@HiltWorker
class CallUploadWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted parameters: WorkerParameters,
    private val uploader: CallUploader,
    private val audio: AudioDrain,
    private val revocation: Revocation,
) : CoroutineWorker(context, parameters) {

    override suspend fun doWork(): Result {
        val outcome = uploader.drainOnce()
        Timber.i(
            "Upload pass: sent=%d confirmed=%d parked=%d",
            outcome.sent, outcome.confirmed, outcome.parked,
        )
        // This drain is where the server's `installation_revoked` is usually
        // heard first, and the answer to it is a deletion (UC-08) — so the
        // enforcement runs here rather than waiting up to fifteen minutes for
        // the heartbeat. It is idempotent and silent when there is nothing
        // left to delete.
        revocation.enforceIfRevoked()

        // Audio follows metadata, always. The server accepts a recording only
        // against a call it already holds, so draining in the other order would
        // upload nothing on the first pass and look like a capture failure.
        val recordings = audio.drainOnce()

        return when {
            // A recording that was interrupted mid-upload resumes from the
            // bytes the server already has; coming back sooner than the
            // fifteen-minute period is worth it for a call somebody is waiting
            // to hear.
            recordings.unfinished > 0 -> Result.retry()

            // More waiting, or the server asked us to come back.
            outcome.retryLater -> Result.retry()
            else -> Result.success()
        }
    }

    companion object {
        private const val ONE_SHOT = "bonvicall.upload.now"
        private const val PERIODIC = "bonvicall.upload.periodic"

        /**
         * Every 15 minutes, which is WorkManager's floor for periodic work.
         *
         * The one-shot below is what makes a call arrive "within minutes" as
         * release 1 requires; this is the safety net for the case where the
         * one-shot was never scheduled because the process died first.
         */
        private const val PERIOD_MINUTES = 15L

        /** Any connection. Restricting to un-metered would mean a salesperson
         *  in the field uploads nothing all day, and N14/N15's cap is enforced
         *  by the data-usage report rather than by refusing to work. */
        private val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        /**
         * Called when a call is queued. Replaces any pending one-shot, so
         * five calls in a row produce one drain rather than five.
         *
         * ⚠️ `REPLACE`, and it was briefly `APPEND_OR_REPLACE` on 2026-09-12 —
         * both measured on the same handset the same afternoon:
         *
         *  • REPLACE cancels a running pass. That was harmless until the
         *    transcoder hung and ignored the cancellation (fixed there, not
         *    here: the pump now runs under `runInterruptible` and unwinds
         *    through `finally`). A cancelled pass loses nothing: jobs already
         *    uploaded are marked done, a chunked upload resumes, a transcode
         *    is redone from an untouched source.
         *  • APPEND_OR_REPLACE chains the new pass BEHIND the existing one —
         *    including one sitting in `Result.retry()` backoff. With one job
         *    answering 409 on every pass, the parent retried with exponential
         *    backoff (attempt 6: sixteen minutes), three appended passes sat
         *    `BLOCKED` behind it, and the CEO's freshly queued call reached
         *    nobody while Moi Zvonki showed the same call in seconds.
         *
         * "A call was queued" means "drain NOW", and REPLACE is the policy
         * that does that.
         */
        fun enqueueNow(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork(
                ONE_SHOT,
                ExistingWorkPolicy.REPLACE,
                OneTimeWorkRequestBuilder<CallUploadWorker>()
                    .setConstraints(constraints)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                    .build(),
            )
        }

        fun schedulePeriodic(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC,
                // KEEP: rescheduling on every service start would reset the
                // period each time an OEM restarts the service, which on a
                // chatty handset means it never actually runs.
                ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<CallUploadWorker>(PERIOD_MINUTES, TimeUnit.MINUTES)
                    .setConstraints(constraints)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
                    .build(),
            )
        }
    }
}
