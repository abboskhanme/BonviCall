package uz.bonvi.call.service.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.service.CaptureSelfMeasurement
import uz.bonvi.call.service.ReconcileSweep
import java.util.concurrent.TimeUnit

/**
 * Runs the reconciliation and recovery sweep (T67), then the self-measurement
 * (T70).
 *
 * Scheduled rather than done inline because both read the call log, which lags
 * the call by seconds to minutes, and because the sweep's most valuable run is
 * the one after a **process death** — a phone whose service was killed
 * overnight has calls that exist only in the OS call log, and only a scheduled
 * worker will still be there to find them.
 */
@HiltWorker
class ReconcileWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted parameters: WorkerParameters,
    private val sweep: ReconcileSweep,
    private val measurement: CaptureSelfMeasurement,
) : CoroutineWorker(context, parameters) {

    override suspend fun doWork(): Result {
        val since = Clock.epochMillis() - LOOKBACK_MS
        val result = sweep.run(since)

        // T70. The only capture-rate metric available on phones nobody can
        // `adb` into, and it has to run after the sweep so the two agree about
        // what was recovered.
        measurement.measureAndReport(since)

        if (result.reconciled > 0 || result.recovered > 0) {
            CallUploadWorker.enqueueNow(applicationContext)
        }
        return Result.success()
    }

    companion object {
        private const val ONE_SHOT = "bonvicall.reconcile.now"
        private const val PERIODIC = "bonvicall.reconcile.periodic"

        /**
         * How far back each sweep looks.
         *
         * Two days, not one: a phone that was off for a weekend must still
         * recover its Friday calls, and re-reading a call already uploaded
         * costs nothing because `client_call_id` makes the upload an upsert.
         */
        private const val LOOKBACK_MS = 2 * 24 * 60 * 60 * 1000L

        private const val PERIOD_MINUTES = 30L

        /** Called after a call ends. The delay lets the call-log row appear —
         *  it is written by the platform after the call, not during it. */
        fun enqueueAfterCall(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork(
                ONE_SHOT,
                ExistingWorkPolicy.REPLACE,
                OneTimeWorkRequestBuilder<ReconcileWorker>()
                    .setInitialDelay(POST_CALL_DELAY_SECONDS, TimeUnit.SECONDS)
                    .build(),
            )
        }

        fun schedulePeriodic(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC,
                ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<ReconcileWorker>(PERIOD_MINUTES, TimeUnit.MINUTES)
                    .build(),
            )
        }

        /** The platform writes the call-log row after the call ends; on some
         *  OEMs a few seconds after. Waiting is cheaper than an unreconciled
         *  record that has to be corrected later. */
        private const val POST_CALL_DELAY_SECONDS = 20L
    }
}
