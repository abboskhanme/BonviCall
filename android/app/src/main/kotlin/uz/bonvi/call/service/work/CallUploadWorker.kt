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
) : CoroutineWorker(context, parameters) {

    override suspend fun doWork(): Result {
        val outcome = uploader.drainOnce()
        Timber.i(
            "Upload pass: sent=%d confirmed=%d parked=%d",
            outcome.sent, outcome.confirmed, outcome.parked,
        )
        return when {
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

        /** Called when a call is queued. Replaces any pending one-shot, so
         *  five calls in a row produce one drain rather than five. */
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
