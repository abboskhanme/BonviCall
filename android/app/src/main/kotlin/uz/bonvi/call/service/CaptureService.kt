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
import uz.bonvi.call.data.repository.CallQueueRepository
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

    /** Tied to the service, not to a call. Cancelled in onDestroy, which is why
     *  it is a scope and not GlobalScope (CONVENTIONS-CLIENT.md §8). */
    private val scope by lazy { CoroutineScope(SupervisorJob() + io) }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startInForeground()
        Timber.i("CaptureService started, variant=%s sdk=%d", BUILD_VARIANT, Capabilities.sdkInt)
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
        scope.cancel()
        super.onDestroy()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // STICKY: if the OS kills us for memory, come back. Whether it honours
        // that is exactly what UC-05 measures, and the app reports
        // service_not_running on its next contact when it does not.
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // The user swiped the app away. The service must survive it — the
        // employee is not opting out of call capture by tidying their recents.
        // T26 schedules the AlarmManager restart here.
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
        private const val CHANNEL_ID = "bonvicall.capture"
        private const val NOTIFICATION_ID = 1001

        /** Sent on every request and stored on every call and heartbeat, so
         *  per-variant capture rate is a query (SPEC §7.2). */
        val BUILD_VARIANT: String get() = uz.bonvi.call.BuildConfig.APP_VARIANT

        fun start(context: Context) {
            context.startForegroundService(Intent(context, CaptureService::class.java))
        }
    }
}
