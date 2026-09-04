package uz.bonvi.call.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.NoOpOemRecordingLocator
import uz.bonvi.call.capture.OemRecordingLocator
import javax.inject.Singleton

/**
 * legacy28 — the ONE flavour-specific Kotlin source (SPEC §7.2).
 *
 * On targetSdk 28 the OEM recordings folder is reachable through
 * `Environment.getExternalStorageDirectory()` and plain `File` objects, so this
 * flavour binds the raw-path locator. Which locator is a CAPABILITY question
 * (`Capabilities.canReadOemRecordingsByPath()`), never a version check — the
 * capture code must not learn what a target SDK is.
 *
 * TODO(T71b): bind `LegacyPathOemRecordingLocator`. It scans, in preference
 * order, `/sdcard/Recordings/Call`, `/sdcard/Recordings/Voice Recorder`,
 * `/sdcard/Call`, `/sdcard/Sounds/Call`, `/sdcard/CallRecordings`
 * (S1-RECORDING.md), read-only, inside the time window only.
 */
@Module
@InstallIn(SingletonComponent::class)
object CaptureModule {

    @Provides
    @Singleton
    fun oemRecordingLocator(): OemRecordingLocator =
        NoOpOemRecordingLocator("legacy28: raw-path locator lands in T71b")
}
