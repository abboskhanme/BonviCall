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
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.UpdateReadiness
import uz.bonvi.call.service.CaptureService
import uz.bonvi.call.service.CommandRunner
import uz.bonvi.call.service.Heartbeat
import uz.bonvi.call.service.Revocation
import uz.bonvi.call.update.AppUpdater
import java.util.concurrent.TimeUnit

/**
 * The phone's regular word to the server (SPEC §4.4, UC-17) — and the caller
 * three finished features were missing.
 *
 * ═══ Why this worker exists ════════════════════════════════════════════════
 * [Heartbeat] built the whole payload and nothing ever sent it; [CommandRunner]
 * could carry out a command nobody collected; [AppUpdater] could install a
 * build nobody offered it. Each had tests, and each test supplied the caller
 * the product did not — which is exactly the failure this build has now met
 * four times. In the panel the symptom was one line: every handset showing as a
 * device that has never reported.
 *
 * ═══ What one pass does ════════════════════════════════════════════════════
 *  1. **Heartbeat.** Queue depth, battery, clock skew, whether capture is
 *     running. This is what `is_online` and the whole device page read.
 *  2. **Commands**, when the answer says some are waiting. The socket is the
 *     fast path (UC-16 wants five seconds); this is how a phone that was asleep
 *     or unreachable still gets them — a dial too old to ring is discarded on
 *     arrival and acknowledged as stale, which is a fact the panel can act on.
 *  3. **The update**, when the server offers a newer build. Never during a
 *     call, and only past the queue when the version gate has already refused
 *     this build (N34) — `UpdateReadiness` owns both rules.
 *  4. **Revocation**, if a request has already learnt the installation is gone
 *     (UC-08). A revoked phone still holding recordings is the worst state this
 *     product has, and it is the one nobody would look for.
 *
 * Fifteen minutes is WorkManager's floor for periodic work, not a chosen
 * interval. `enqueueNow` covers the two moments where waiting is wrong: the end
 * of enrolment, and a service start.
 */
@HiltWorker
class HeartbeatWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted parameters: WorkerParameters,
    private val heartbeat: Heartbeat,
    private val commands: CommandRunner,
    private val updater: AppUpdater,
    private val revocation: Revocation,
    private val session: SessionStore,
    private val queue: CallQueueRepository,
) : CoroutineWorker(context, parameters) {

    override suspend fun doWork(): Result {
        if (session.snapshot.installationId == null) {
            // Not enrolled. There is nothing to report and nobody to report to.
            return Result.success()
        }

        // Whatever else happens, a phone the server has revoked must not be
        // left holding audio — and this runs even when the heartbeat cannot
        // reach anyone, because the flag was set by an earlier request.
        revocation.enforceIfRevoked()

        val result = heartbeat.send()
            // Offline. Not a failure worth retrying with backoff: the periodic
            // pass comes back, and a missed heartbeat is itself how the panel
            // learns a phone is out of contact (`device_offline_minutes`).
            ?: return Result.success()

        // The heartbeat reached the server, so there IS network — which makes
        // this the cheapest moment to notice the service is gone. The watchdog
        // covers the same ground on its own fifteen-minute schedule; doing it
        // here as well halves the average time a frozen handset spends not
        // capturing, and costs one boolean when everything is fine.
        restartCaptureIfStopped()

        // The same proof of reachability rescues the queue. Rows parked only
        // because nobody answered are given back here and nowhere else: this
        // is the one place in the app that knows, from a real response, that
        // the server is there again. Without it the fix to [UploadPolicy] only
        // helps calls captured from now on, and the ones already parked — 39 of
        // them on the first real handset — would stay on the phone for ever.
        queue.unparkUnreachable()

        if (result.pendingCommands > 0) {
            val handled = commands.drain()
            Timber.i("Heartbeat collected %d command(s)", handled)
        }

        offerUpdate(result)
        return Result.success()
    }

    @Suppress("TooGenericExceptionCaught")
    private fun restartCaptureIfStopped() {
        if (CaptureService.isRunning) return
        try {
            CaptureService.start(applicationContext)
        } catch (error: Exception) {
            // API 31+ refuses a foreground start from the background unless the
            // app is exempt from battery optimisation. Not fatal: the phone
            // reports `service_not_running` on this very heartbeat, so the
            // panel can see it, and opening the app fixes it immediately.
            Timber.w(error, "Could not restart capture from the heartbeat")
        }
    }

    /**
     * Install an update **only when the server has stopped accepting this
     * build** (N34).
     *
     * ⚠️ Deliberately not "whenever a newer version exists". Installing an APK
     * opens the OS installer over whatever the person is doing, and a phone
     * that merely *could* update would meet that dialog every fifteen minutes
     * until they gave in — on a handset they own. Raising the minimum version
     * is the lever the panel already has, and it is the one that means "this
     * build must go".
     *
     * The rest of the decision belongs to [AppUpdater]: never during a call,
     * and past the queue only because the server is refusing this build anyway
     * — the calls stay on disk either way, which is the promise N34 makes.
     */
    private suspend fun offerUpdate(result: Heartbeat.Result) {
        if (!result.updateRequired) return

        val offered = result.latestVersionCode ?: result.minVersionCode
        if (!UpdateReadiness.isNewer(offered, uz.bonvi.call.BuildConfig.VERSION_CODE)) return

        when (val outcome = updater.update(offered, forced = true)) {
            is AppUpdater.Result.InstallerLaunched ->
                Timber.i("Update %d: the installer is open", offered)
            is AppUpdater.Result.Deferred ->
                Timber.i("Update %d deferred: %s", offered, outcome.decision)
            is AppUpdater.Result.Failed ->
                Timber.w("Update %d refused: %s", offered, outcome.reason)
        }
    }

    companion object {
        private const val ONE_SHOT = "bonvicall.heartbeat.now"
        private const val PERIODIC = "bonvicall.heartbeat.periodic"
        private const val PERIOD_MINUTES = 15L

        private val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        /**
         * Now, not in fifteen minutes.
         *
         * Called when enrolment finishes and when the service starts. The
         * first is why a phone appears in the panel as alive within seconds of
         * the agent seeing "Tayyor" — which is what an admin watching a
         * rollout is actually waiting for.
         */
        fun enqueueNow(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork(
                ONE_SHOT,
                ExistingWorkPolicy.REPLACE,
                OneTimeWorkRequestBuilder<HeartbeatWorker>()
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
                PeriodicWorkRequestBuilder<HeartbeatWorker>(PERIOD_MINUTES, TimeUnit.MINUTES)
                    .setConstraints(constraints)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
                    .build(),
            )
        }
    }
}
