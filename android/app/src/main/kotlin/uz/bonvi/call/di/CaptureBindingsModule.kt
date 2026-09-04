package uz.bonvi.call.di

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.CaptureCapabilityChecker
import uz.bonvi.call.capture.PermissionCaptureCapabilityChecker
import uz.bonvi.call.data.repository.RoomCallSessionStore
import uz.bonvi.call.service.CallSessionStore
import javax.inject.Singleton

/**
 * Capture bindings shared by BOTH flavours.
 *
 * The flavour-specific `di/CaptureModule.kt` binds ONE thing — which
 * `OemRecordingLocator` this build uses — and nothing else (SPEC §7.2). Every
 * other capture binding lives here so a change does not have to be made twice
 * and cannot be made twice differently.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class CaptureBindingsModule {

    @Binds
    @Singleton
    abstract fun captureCapabilityChecker(
        impl: PermissionCaptureCapabilityChecker,
    ): CaptureCapabilityChecker

    @Binds
    @Singleton
    abstract fun callSessionStore(impl: RoomCallSessionStore): CallSessionStore
}
