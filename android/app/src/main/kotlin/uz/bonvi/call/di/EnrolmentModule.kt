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
import uz.bonvi.call.enrolment.CaptureServiceState
import uz.bonvi.call.enrolment.DeviceFacts
import uz.bonvi.call.enrolment.StepTimer
import uz.bonvi.call.enrolment.StorageAccessProbe
import uz.bonvi.call.enrolment.SubscriptionPresenceProbe
import uz.bonvi.call.service.CaptureService
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
    fun captureServiceState(): CaptureServiceState = CaptureServiceState {
        CaptureService.isRunning
    }

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
