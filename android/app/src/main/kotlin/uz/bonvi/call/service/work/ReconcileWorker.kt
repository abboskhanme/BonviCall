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
        if (result.stillWaiting > 0) {
            // A finished call whose call-log row has not appeared yet. Come
            // back in seconds, not in thirty minutes: the row is written by
            // the platform within a second or two of hang-up, and the first
            // sweep is deliberately early. The delay escalates (4, 8, 16, 32,
            // then 60 s) so a row that never comes costs a few sweeps an hour
            // until the fifteen-minute deadline ships the call on its live id.
            val attempt = inputData.getInt(KEY_ATTEMPT, 0) + 1
            enqueueAfterCall(applicationContext, attempt)
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

        /**
         * Called after a call ends (attempt 0), and by the worker itself while
         * a finished call is still waiting for its call-log row.
         *
         * A call end REPLACES whatever is pending — the newest call is the one
         * to serve. A retry APPENDS behind the running worker instead, so it
         * cannot cancel the pass that scheduled it.
         */
        fun enqueueAfterCall(context: Context, attempt: Int = 0) {
            WorkManager.getInstance(context).enqueueUniqueWork(
                ONE_SHOT,
                if (attempt == 0) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.APPEND_OR_REPLACE,
                OneTimeWorkRequestBuilder<ReconcileWorker>()
                    .setInitialDelay(delaySeconds(attempt), TimeUnit.SECONDS)
                    .setInputData(androidx.work.Data.Builder().putInt(KEY_ATTEMPT, attempt).build())
                    .build(),
            )
        }

        /**
         * How long to wait before sweep number [attempt] for one call.
         *
         * Attempt 0 is the sweep after hang-up. It was 20 s — "the platform
         * writes the row after the call, on some OEMs a few seconds after" —
         * and those 20 s were the larger part of the metadata's delay on a
         * fleet where the row appears within about two seconds (measured
         * 2026-09-12). Four seconds covers that with margin; a late row is
         * retried on the escalating schedule rather than paid for on every
         * call.
         */
        fun delaySeconds(attempt: Int): Long =
            if (attempt <= 0) FIRST_DELAY_SECONDS else minOf(FIRST_DELAY_SECONDS shl attempt.coerceAtMost(5), MAX_RETRY_DELAY_SECONDS)

        fun schedulePeriodic(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC,
                ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<ReconcileWorker>(PERIOD_MINUTES, TimeUnit.MINUTES)
                    .build(),
            )
        }

        private const val KEY_ATTEMPT = "attempt"
        const val FIRST_DELAY_SECONDS = 4L
        const val MAX_RETRY_DELAY_SECONDS = 60L
    }
}
