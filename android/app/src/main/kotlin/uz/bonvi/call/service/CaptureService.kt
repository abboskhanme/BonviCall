package uz.bonvi.call.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.telephony.TelephonyManager
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import android.content.pm.ServiceInfo
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import timber.log.Timber
import uz.bonvi.call.R
import uz.bonvi.call.core.Capabilities
import android.app.AlarmManager
import android.app.PendingIntent
import android.os.SystemClock
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.service.work.CallUploadWorker
import uz.bonvi.call.service.work.HeartbeatWorker
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

    /** The enrolled SIM, as a flow — see the registration block in [onCreate]. */
    @Inject lateinit var session: SessionStore

    /** UC-16's five-second bar. Held open for as long as this service lives. */
    @Inject lateinit var realtime: RealtimeChannel

    /** Held to release the microphone, never to start anything from here. */
    @Inject lateinit var capture: CallCapture

    /** Held for the whole service lifetime — see [acquireWakeLock]. */
    private var wakeLock: PowerManager.WakeLock? = null

    /** Tied to the service, not to a call. Cancelled in onDestroy, which is why
     *  it is a scope and not GlobalScope (CONVENTIONS-CLIENT.md §8). */
    private val scope by lazy { CoroutineScope(SupervisorJob() + io) }

    override fun onBind(intent: Intent?): IBinder? = null

    private val PHONE_CALL_AND_MICROPHONE: Int
        get() = ServiceInfo.FOREGROUND_SERVICE_TYPE_PHONE_CALL or
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE

    private val MICROPHONE_AND_DATA_SYNC: Int
        get() = ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC

    /** The type that needs no runtime permission at all — see the candidate
     *  list in [startInForeground]. */
    private val DATA_SYNC_ONLY: Int
        get() = ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC

    override fun onCreate() {
        super.onCreate()
        createChannel()
        acquireWakeLock()
        startInForeground()
        isRunning = true
        Timber.i("CaptureService started, variant=%s sdk=%d", BUILD_VARIANT, Capabilities.sdkInt)

        // The LIVE call-state source. The manifest receiver covers the cold
        // case where this process is not running; both are needed, because a
        // phone that has not been opened since a reboot still takes calls.
        callStateSource.register(scope)

        // ⚠️ And AGAIN whenever the enrolled SIM becomes known or changes.
        // The call above runs before SessionStore has read its DataStore, so
        // on a fresh process it usually finds no SIM and declines — which,
        // with nothing to call it back, left the live source off for the
        // life of the process and every call to a receiver whose broadcast
        // names no subscription (2026-09-12). The id is passed from the
        // emission itself so the snapshot's own timing cannot matter, and
        // `register` is idempotent for the id it already holds.
        scope.launch {
            session.simSubscriptionId
                .filterNotNull()
                .distinctUntilChanged()
                .collect { subscriptionId -> callStateSource.register(scope, subscriptionId) }
        }

        // The command channel. A dial expires after two minutes, so the
        // fifteen-minute heartbeat can only ever collect one too late to ring —
        // this is what makes click-to-call a feature rather than a record of
        // failures.
        realtime.connect(scope)

        // Four survival mechanisms, and the fleet needs all four (UC-05):
        // START_STICKY, BOOT_COMPLETED, onTaskRemoved below, and this watchdog
        // for "the OS stopped it and told nobody".
        WatchdogWorker.schedule(this)
        CallUploadWorker.schedulePeriodic(this)
        ReconcileWorker.schedulePeriodic(this)

        // UC-17. Nothing sent a heartbeat until this line existed, so every
        // handset in the panel was a device that had never reported — which
        // during a rollout is indistinguishable from an install that failed.
        // One now, because a service start is exactly the event an admin is
        // watching for, and then every fifteen minutes.
        HeartbeatWorker.schedulePeriodic(this)
        HeartbeatWorker.enqueueNow(this)

        // A start is also a recovery point: calls made while this service was
        // dead exist only in the OS call log until the sweep finds them
        // (UC-13). Running it on every start is what makes an overnight kill
        // cost minutes rather than a night of calls.
        ReconcileWorker.enqueueAfterCall(this)

        resumeInFlightCalls()
        watchForAbandonedCapture()
    }

    /**
     * Release the microphone when the line is idle and something is still
     * recording.
     *
     * ═══════════════════════════════════════════════════════════════════════
     * A capture is stopped by the call ending — when the app is told the call
     * ended. On MIUI it sometimes is not: the state callback is throttled or
     * dropped while the app is in the background, and the recorder then runs
     * against an idle line for ever. That is not a lost recording, which the
     * gap report would at least show: it is this app holding a microphone that
     * belongs to somebody's personal phone, and every other app on it —
     * Telegram was the one the fleet noticed — recording silence until they
     * reboot.
     *
     * Two consecutive idle checks, not one: a stop is asynchronous, so the
     * line is briefly idle while the legitimate capture finishes writing its
     * file, and cutting that would corrupt the recording this product exists
     * for.
     * ═══════════════════════════════════════════════════════════════════════
     */
    private fun watchForAbandonedCapture() {
        scope.launch {
            var idleChecks = 0
            while (isActive) {
                delay(ABANDONED_CHECK_MS)
                if (!capture.isCapturing()) {
                    idleChecks = 0
                    continue
                }
                if (!lineIsIdle()) {
                    idleChecks = 0
                    continue
                }
                idleChecks++
                if (idleChecks >= ABANDONED_CHECKS) {
                    Timber.w("Capture still running on an idle line; releasing the microphone")
                    @Suppress("TooGenericExceptionCaught")
                    try {
                        capture.releaseAll()
                    } catch (error: Exception) {
                        Timber.w(error, "Could not release an abandoned capture")
                    }
                    idleChecks = 0
                }
            }
        }
    }

    /** True when the telephony stack says no call is in progress. Unknown
     *  counts as NOT idle: a watchdog that guesses would cut live calls. */
    private fun lineIsIdle(): Boolean =
        @Suppress("TooGenericExceptionCaught")
        try {
            val telephony = getSystemService(TelephonyManager::class.java)
            telephony?.callState == TelephonyManager.CALL_STATE_IDLE
        } catch (error: Exception) {
            Timber.w(error, "Could not read the call state")
            false
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

        // ⚠️ THE MICROPHONE FIRST. This service is destroyed mid-call on any
        // handset with an aggressive battery manager, which is most of this
        // fleet — and the coordinator is a singleton that outlives it, so a
        // `MediaRecorder` started for that call went on holding the microphone
        // for as long as the PROCESS lived. On a targetSdk 28 build the
        // platform grants that hold outright: on 2026-09-15 the fleet reported
        // that Telegram could not place a call and recorded voice messages as
        // silence, and reinstalling with the targetSdk 34 flavour "fixed" it
        // because the newer platform refuses the hold rather than because the
        // leak was gone.
        //
        // The recording is lost either way once this service goes; the
        // microphone must not be.
        @Suppress("TooGenericExceptionCaught")
        try {
            capture.releaseAll()
        } catch (error: Exception) {
            Timber.w(error, "Could not release capture on service destroy")
        }

        releaseWakeLock()
        callStateSource.unregister()
        realtime.disconnect()
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

        // ═══ The type is CHOSEN AT RUNTIME, best first ═════════════════════
        //
        // `phoneCall` is the type this service actually is, and it is the one
        // the OS treats accordingly: it is exempt from Android 15's six-hour
        // `dataSync` budget, and it may be restarted from the background —
        // which is exactly what the watchdog does after an OEM kill. It needs
        // `MANAGE_OWN_CALLS`, which the manifest now declares; the previous
        // reasoning ("the app does not qualify") was true only because that
        // permission was absent. CallSentry qualified the same way and stayed
        // alive on the same handsets.
        //
        // Declared but not assumed: starting an FGS of a type the app does not
        // qualify for throws, so each candidate is tried and the first that
        // takes wins. What actually took is recorded on [activeType] and
        // surfaces in the `foreground_service` capability — a measurement on
        // the real fleet rather than an argument about the documentation.
        // ⚠️ The third candidate is not decoration. From API 34 the
        // `microphone` type requires RECORD_AUDIO to be **granted**, and an
        // agent is allowed to decline it (UC-14: a phone that logs calls
        // without audio is a supported state). Without a microphone-free
        // candidate both of the first two throw, the untyped fallback below
        // inherits the manifest's types and throws for the same reason, and
        // the service does not start at all — so a phone that should have
        // logged calls without audio logs nothing and reports nothing.
        // `dataSync` needs no runtime permission and always leaves something
        // running.
        val candidates = listOf(
            PHONE_CALL_AND_MICROPHONE to "phoneCall|microphone",
            MICROPHONE_AND_DATA_SYNC to "microphone|dataSync",
            DATA_SYNC_ONLY to "dataSync",
        )
        for ((type, name) in candidates) {
            @Suppress("TooGenericExceptionCaught")
            try {
                ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, type)
                activeType = name
                Timber.i("Foreground service running as %s", name)
                return
            } catch (error: Exception) {
                // SecurityException on a type this app does not qualify for;
                // ForegroundServiceStartNotAllowedException when the OS refuses
                // a background start of a while-in-use type. Neither may take
                // the service down — a phone that captures with a lesser type
                // is worth more than one that crashed choosing it.
                Timber.w("Foreground type %s refused (%s)", name, error.javaClass.simpleName)
            }
        }

        // Last resort: no type at all. Legal below API 29 and the honest
        // fallback above it — the service runs, and `activeType` says what the
        // panel is looking at.
        @Suppress("TooGenericExceptionCaught")
        try {
            startForeground(NOTIFICATION_ID, notification)
            activeType = "untyped"
        } catch (error: Exception) {
            activeType = null
            Timber.e(error, "The OS refused the foreground service entirely")
        }
    }

    /**
     * Hold the CPU for as long as the service lives (UC-05).
     *
     * **This is what CallSentry had and this app did not.** Doze and the OEM
     * power managers kill a socket and defer a periodic worker silently; a
     * partial wake lock is what keeps the capture service and its command
     * channel alive through the night. The first real handset went quiet 19
     * minutes after the screen went off — no socket, and the fifteen-minute
     * heartbeat never ran.
     *
     * Not reference-counted and released in [onDestroy], so there is exactly
     * one acquire and one release. `WAKE_LOCK` has been declared since T22 for
     * precisely this and was never used.
     */
    private fun acquireWakeLock() {
        @Suppress("TooGenericExceptionCaught")
        try {
            val power = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_LOCK_TAG).apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (error: Exception) {
            // An OEM that refuses the lock is a phone that will sleep through
            // its calls, and the gap report is where that shows up. It is not a
            // reason to refuse to run.
            Timber.w(error, "Could not hold a wake lock")
        }
    }

    private fun releaseWakeLock() {
        @Suppress("TooGenericExceptionCaught")
        try {
            wakeLock?.takeIf { it.isHeld }?.release()
        } catch (error: Exception) {
            Timber.w(error, "Wake lock was already gone")
        }
        wakeLock = null
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

        /**
         * Which foreground-service type the OS actually accepted.
         *
         * Read by the `foreground_service` capability, so the panel shows what
         * each handset is running as. `phoneCall|microphone` is the one that
         * survives Android 15's `dataSync` budget and a background restart.
         */
        @Volatile
        var activeType: String? = null
            private set

        private const val WAKE_LOCK_TAG = "BonviCall:CaptureService"

        private const val CHANNEL_ID = "bonvicall.capture"
        private const val NOTIFICATION_ID = 1001
        private const val RESTART_REQUEST = 2001

        /** Long enough for the process to finish dying, short enough that a
         *  call placed straight after a swipe is still captured. */
        /** Every 20 s while a capture is running: often enough that nobody
         *  finishes a voice message into a blocked microphone, rare enough to
         *  cost nothing. */
        private const val ABANDONED_CHECK_MS = 20_000L

        /** Two idle readings in a row — a stop is asynchronous, and one is
         *  normal while a real capture is being written out. */
        private const val ABANDONED_CHECKS = 2

        private const val RESTART_DELAY_MS = 1_000L

        /** Sent on every request and stored on every call and heartbeat, so
         *  per-variant capture rate is a query (SPEC §7.2). */
        val BUILD_VARIANT: String get() = uz.bonvi.call.BuildConfig.APP_VARIANT

        /**
         * Start the service, and **never throw doing it**.
         *
         * From API 31 a background `startForegroundService` is refused with
         * `ForegroundServiceStartNotAllowedException` unless the app is
         * exempt — and the exemption this app relies on is the
         * battery-optimisation one E2 asks for, which an agent is allowed to
         * decline (UC-14). Every caller here is a place where throwing is
         * worse than not starting:
         *
         *  • [PhoneStateReceiver] — an uncaught exception in `onReceive`
         *    crashes the app **on every incoming call**, which is
         *    indistinguishable from the app being broken;
         *  • [BootReceiver] — a crash at boot, before anybody has opened it;
         *  • `WatchdogWorker` — the one mechanism that recovers from an OEM
         *    kill would itself die.
         *
         * A refusal is logged and reported as `service_not_running` on the
         * next contact, which is the state the panel is watching for. That is
         * the honest outcome: the phone says it is not capturing rather than
         * disappearing.
         */
        fun start(context: Context) {
            @Suppress("TooGenericExceptionCaught")
            try {
                context.startForegroundService(Intent(context, CaptureService::class.java))
            } catch (error: Exception) {
                Timber.w(
                    error,
                    "The OS refused to start the capture service (%s)",
                    error.javaClass.simpleName,
                )
            }
        }
    }
}
