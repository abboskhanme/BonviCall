package uz.bonvi.call.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import timber.log.Timber
import uz.bonvi.call.R
import uz.bonvi.call.core.Capabilities
import android.app.AlarmManager
import android.app.PendingIntent
import android.os.SystemClock
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.service.work.CallUploadWorker
import uz.bonvi.call.service.work.ReconcileWorker
import uz.bonvi.call.service.work.WatchdogWorker
import uz.bonvi.call.di.IoDispatcher
import kotlinx.coroutines.CoroutineDispatcher
import javax.inject.Inject

/**
 * The foreground service that owns the call state machine (SPEC §7.5).
 *
 * T22 gives it a lifecycle and a notification and nothing else — T26 adds call
 * detection, T71 the capture routing, T74 the upload. What is settled here is
 * the part every later task depends on: the service starts in the foreground
 * immediately, it is restarted by [BootReceiver], and its notification says in
 * Uzbek what is being recorded and for which number. N41's transparency begins
 * on that notification, which the employee sees every day on their own phone —
 * a blank "app is running" would be worse than no app.
 */
@AndroidEntryPoint
class CaptureService : Service() {

    @Inject lateinit var sessions: CallSessionManager

    @Inject lateinit var queue: CallQueueRepository

    @Inject @IoDispatcher lateinit var io: CoroutineDispatcher

    @Inject lateinit var callStateSource: TelephonyCallbackSource

    /** Tied to the service, not to a call. Cancelled in onDestroy, which is why
     *  it is a scope and not GlobalScope (CONVENTIONS-CLIENT.md §8). */
    private val scope by lazy { CoroutineScope(SupervisorJob() + io) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startInForeground()
        isRunning = true
        Timber.i("CaptureService started, variant=%s sdk=%d", BUILD_VARIANT, Capabilities.sdkInt)

        // The LIVE call-state source. The manifest receiver covers the cold
        // case where this process is not running; both are needed, because a
        // phone that has not been opened since a reboot still takes calls.
        callStateSource.register(scope)

        // Four survival mechanisms, and the fleet needs all four (UC-05):
        // START_STICKY, BOOT_COMPLETED, onTaskRemoved below, and this watchdog
        // for "the OS stopped it and told nobody".
        WatchdogWorker.schedule(this)
        CallUploadWorker.schedulePeriodic(this)
        ReconcileWorker.schedulePeriodic(this)

        // A start is also a recovery point: calls made while this service was
        // dead exist only in the OS call log until the sweep finds them
        // (UC-13). Running it on every start is what makes an overnight kill
        // cost minutes rather than a night of calls.
        ReconcileWorker.enqueueAfterCall(this)

        resumeInFlightCalls()
    }

    /**
     * UC-05. The service is killed between a call ending and its audio being
     * queued on any handset with an aggressive battery manager — which is most
     * of the fleet — so a start is a RESUME, not a restart. A call caught
     * mid-reconciliation is finished rather than lost, and the queue depth is
     * logged because "how many calls are waiting" is the first question during
     * an assisted install (UC-07).
     */
    private fun resumeInFlightCalls() {
        scope.launch {
            val resumed = sessions.resume()
            val depth = queue.depth()
            Timber.i(
                "Resumed %d call session(s); queue: %d pending, %d parked, %d bytes",
                resumed.size,
                depth.pending,
                depth.parked,
                depth.bytes,
            )
        }
    }

    override fun onDestroy() {
        isRunning = false
        callStateSource.unregister()
        scope.cancel()
        super.onDestroy()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // STICKY: if the OS kills us for memory, come back. Whether it honours
        // that is exactly what UC-05 measures, and the app reports
        // service_not_running on its next contact when it does not.
        return START_STICKY
    }

    /**
     * The user swiped the app out of recents.
     *
     * The service must survive it: the employee is not opting out of call
     * capture by tidying their recents, and on several OEMs a swipe kills the
     * whole process including a foreground service. An `AlarmManager` one-shot
     * a second out is the only mechanism that runs after the process is gone.
     *
     * `setExactAndAllowWhileIdle` because doze would otherwise defer it to the
     * next maintenance window, which can be hours — and the calls made in those
     * hours are the ones this exists to keep.
     */
    override fun onTaskRemoved(rootIntent: Intent?) {
        val restart = PendingIntent.getService(
            this,
            RESTART_REQUEST,
            Intent(this, CaptureService::class.java),
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE,
        )
        val alarms = getSystemService(AlarmManager::class.java)
        alarms?.setExactAndAllowWhileIdle(
            AlarmManager.ELAPSED_REALTIME_WAKEUP,
            SystemClock.elapsedRealtime() + RESTART_DELAY_MS,
            restart,
        )
        Timber.i("Task removed; capture service will restart in %d ms", RESTART_DELAY_MS)
        super.onTaskRemoved(rootIntent)
    }

    private fun createChannel() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.service_channel_name),
            // LOW, not MIN: MIN lets some OEM launchers hide the notification,
            // and a hidden capture notification is the opposite of N41.
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.service_channel_description)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun startInForeground() {
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.service_notification_title))
            .setContentText(getString(R.string.service_notification_text))
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

        // The TYPE is declared in the manifest, per flavour: legacy28 runs
        // microphone|dataSync, modern34 adds phoneCall. Passing the type here
        // as well would be a second place to keep in step, and on API 34 the
        // wrong one throws (see src/modern34/AndroidManifest.xml).
        startForeground(NOTIFICATION_ID, notification)
    }

    companion object {
        /**
         * Whether the service is running RIGHT NOW.
         *
         * The `foreground_service` capability asks "is it running", not "was it
         * started", and `ActivityManager.getRunningServices` answers neither
         * usefully from API 26 (it only reports the caller's own services). A
         * flag the service maintains is the honest answer.
         */
        @Volatile
        var isRunning: Boolean = false
            private set

        private const val CHANNEL_ID = "bonvicall.capture"
        private const val NOTIFICATION_ID = 1001
        private const val RESTART_REQUEST = 2001

        /** Long enough for the process to finish dying, short enough that a
         *  call placed straight after a swipe is still captured. */
        private const val RESTART_DELAY_MS = 1_000L

        /** Sent on every request and stored on every call and heartbeat, so
         *  per-variant capture rate is a query (SPEC §7.2). */
        val BUILD_VARIANT: String get() = uz.bonvi.call.BuildConfig.APP_VARIANT

        fun start(context: Context) {
            context.startForegroundService(Intent(context, CaptureService::class.java))
        }
    }
}
