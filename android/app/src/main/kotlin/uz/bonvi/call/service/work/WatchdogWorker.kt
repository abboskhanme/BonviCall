package uz.bonvi.call.service.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import timber.log.Timber
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.service.CaptureService
import java.util.concurrent.TimeUnit

/**
 * Restarts the capture service when the OS has killed it (UC-05, T69).
 *
 * The service is `START_STICKY`, restarts on boot, and restarts on
 * `onTaskRemoved`. None of that is enough on the handsets this fleet actually
 * runs: an OEM battery manager will stop a foreground service and simply not
 * restart it, and the app has no way to know until something asks. A
 * fifteen-minute watchdog is the last of the four mechanisms and the only one
 * that covers "the OS decided to, and told nobody".
 *
 * Fifteen minutes is WorkManager's floor for periodic work, not a chosen
 * interval — it is the fastest guarantee available without a second foreground
 * service.
 *
 * It starts nothing before there is an installation to capture for: a
 * notification on the phone of somebody who has not finished enrolling is worse
 * than no capture, because it is the first thing they will switch off.
 */
@HiltWorker
class WatchdogWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted parameters: WorkerParameters,
    private val session: SessionStore,
) : CoroutineWorker(context, parameters) {

    override suspend fun doWork(): Result {
        if (session.snapshot.installationId == null) {
            // Not enrolled. Nothing to capture, nothing to restart.
            return Result.success()
        }
        if (CaptureService.isRunning) return Result.success()

        // If the OS refuses the start, the app reports `service_not_running` on
        // its next contact rather than going quiet (SPEC §7.5) — a silent
        // absence is indistinguishable from a quiet day.
        Timber.w("Capture service was not running; restarting it")
        @Suppress("TooGenericExceptionCaught")
        return try {
            CaptureService.start(context)
            Result.success()
        } catch (error: Exception) {
            // Broad, and the specific failure is `ForegroundServiceStartNot
            // AllowedException` on API 31+ when the app is in the background.
            // Retrying is right: the next window may allow it.
            Timber.e(error, "Could not restart the capture service")
            Result.retry()
        }
    }

    companion object {
        private const val NAME = "bonvicall.watchdog"
        private const val PERIOD_MINUTES = 15L

        fun schedule(context: Context) {
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<WatchdogWorker>(PERIOD_MINUTES, TimeUnit.MINUTES)
                    .build(),
            )
        }
    }
}
