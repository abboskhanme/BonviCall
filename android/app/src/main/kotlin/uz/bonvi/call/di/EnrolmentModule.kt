package uz.bonvi.call.di

import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.EnrolledSubscriptionPresenceProbe
import uz.bonvi.call.capture.OemFolderStorageAccessProbe
import uz.bonvi.call.capture.TelephonySimDirectory
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.EnrolledSubscription
import uz.bonvi.call.domain.SimDirectory
import uz.bonvi.call.capture.EnrolmentFacts
import uz.bonvi.call.enrolment.AndroidDeviceFacts
import uz.bonvi.call.enrolment.CaptureLauncher
import uz.bonvi.call.enrolment.CaptureServiceState
import uz.bonvi.call.enrolment.DeviceFacts
import uz.bonvi.call.enrolment.StepTimer
import uz.bonvi.call.enrolment.StorageAccessProbe
import uz.bonvi.call.enrolment.SubscriptionPresenceProbe
import uz.bonvi.call.service.CallEndedListener
import uz.bonvi.call.service.CaptureService
import uz.bonvi.call.service.work.HeartbeatWorker
import uz.bonvi.call.service.work.ReconcileWorker
import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import javax.inject.Singleton

/**
 * The enrolment graph.
 *
 * Every probe behind E2 is bound here rather than constructed at a call site,
 * for the reason SPEC §7.8 gives: **each capability is checked by exercising
 * it**, and a checker that a screen constructs itself is a checker a screen can
 * quietly replace with a boolean.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class EnrolmentModule {

    @Binds
    @Singleton
    abstract fun deviceFacts(impl: AndroidDeviceFacts): DeviceFacts

    @Binds
    @Singleton
    abstract fun storageAccessProbe(impl: OemFolderStorageAccessProbe): StorageAccessProbe

    @Binds
    @Singleton
    abstract fun simDirectory(impl: TelephonySimDirectory): SimDirectory

    @Binds
    @Singleton
    abstract fun subscriptionPresence(
        impl: EnrolledSubscriptionPresenceProbe,
    ): SubscriptionPresenceProbe
}

@Module
@InstallIn(SingletonComponent::class)
object EnrolmentProviders {

    /**
     * Whether the capture service is up.
     *
     * A flag the service itself sets, rather than `ActivityManager`'s running
     * services: from API 26 that API only reports the caller's own services
     * anyway, and it answers "was it started", where the capability question is
     * "is it running now" (SPEC §7.8).
     */
    @Provides
    @Singleton
    fun captureServiceState(): CaptureServiceState = object : CaptureServiceState {
        override fun isCaptureServiceRunning(): Boolean = CaptureService.isRunning
        override fun captureServiceType(): String? = CaptureService.activeType
    }

    /**
     * What "Tayyor" does besides say so.
     *
     * The service is started and a heartbeat is sent immediately, so a phone
     * that has just finished enrolling appears in the panel as alive within
     * seconds rather than whenever the first call, a reboot or the
     * fifteen-minute watchdog happened to wake it. Before this existed, a
     * correctly enrolled handset looked exactly like a failed install for as
     * long as nobody rang it.
     *
     * The start cannot throw: on API 31+ the OS refuses a foreground service
     * started from the background, and an exception on the last screen of
     * enrolment would undo a successful install. That guarantee lives in
     * [CaptureService.start] itself — every caller needs it, not just this one
     * — so there is one place it is made rather than a try/catch per call
     * site, one of which would eventually be forgotten. The watchdog covers
     * the refusal fifteen minutes later.
     */
    @Provides
    @Singleton
    fun captureLauncher(@ApplicationContext context: Context): CaptureLauncher =
        CaptureLauncher {
            CaptureService.start(context)
            HeartbeatWorker.enqueueNow(context)
        }

    /**
     * A finished call schedules the reconciliation sweep.
     *
     * Bound here rather than called from `CallDetector` so the detector stays
     * free of WorkManager and its decisions stay unit-testable.
     */
    @Provides
    @Singleton
    fun callEndedListener(@ApplicationContext context: Context): CallEndedListener =
        CallEndedListener { ReconcileWorker.enqueueAfterCall(context) }

    /** One timer per enrolment attempt is wrong — N40 measures the whole run,
     *  across screens, so it is a singleton for the process. */
    @Provides
    @Singleton
    fun stepTimer(): StepTimer = StepTimer()

    /**
     * What the privacy boundary judges against, read from the session.
     *
     * Guard 1 asks this on every call, so it must be a cheap synchronous read —
     * hence the DataStore snapshot rather than a suspending flow collect.
     */
    @Provides
    @Singleton
    fun enrolmentFacts(session: SessionStore): EnrolmentFacts = EnrolmentFacts {
        EnrolledSubscription(
            subscriptionId = session.snapshot.simSubscriptionId,
            registeredNumber = session.snapshot.registeredNumberE164,
            isActive = session.snapshot.installationId != null,
        )
    }
}
