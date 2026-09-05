package uz.bonvi.call.di

import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.CaptureCapabilityChecker
import uz.bonvi.call.capture.PermissionCaptureCapabilityChecker
import uz.bonvi.call.capture.SubscriptionPrivacyBoundary
import uz.bonvi.call.capture.transcode.AudioTranscoder
import uz.bonvi.call.capture.transcode.MediaCodecAudioTranscoder
import uz.bonvi.call.data.repository.AudioUpload
import uz.bonvi.call.data.repository.AudioUploader
import uz.bonvi.call.data.player.Media3AudioPlayback
import uz.bonvi.call.data.repository.RetrofitMyCallsGateway
import uz.bonvi.call.data.repository.RoomCallSessionStore
import uz.bonvi.call.data.repository.RoomPendingCallStore
import uz.bonvi.call.domain.AudioPlayback
import uz.bonvi.call.domain.MyCallsGateway
import uz.bonvi.call.domain.PrivacyBoundary
import uz.bonvi.call.service.CallSessionStore
import uz.bonvi.call.service.PendingCallStore
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

    @Binds
    @Singleton
    abstract fun audioTranscoder(impl: MediaCodecAudioTranscoder): AudioTranscoder

    @Binds
    @Singleton
    abstract fun audioUpload(impl: AudioUploader): AudioUpload

    @Binds
    @Singleton
    abstract fun myCallsGateway(impl: RetrofitMyCallsGateway): MyCallsGateway

    @Binds
    @Singleton
    abstract fun audioPlayback(impl: Media3AudioPlayback): AudioPlayback

    @Binds
    @Singleton
    abstract fun pendingCallStore(impl: RoomPendingCallStore): PendingCallStore

    /** Guard 1's one implementation. Bound here so nothing can construct a
     *  second boundary with different rules (CONVENTIONS.md §8). */
    @Binds
    @Singleton
    abstract fun privacyBoundary(impl: SubscriptionPrivacyBoundary): PrivacyBoundary
}
