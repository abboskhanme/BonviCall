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

    /**
     * ⚠️ **T71b is a change to this one function and nothing else.**
     *
     * The seam around it is finished: `OemHarvestStrategy` already takes the
     * `Decision.Capture` proof and hands it here, `CaptureRouter` already
     * starts this route first and records which one won, the window constants
     * and the retry are already in `OemRecordingLocator`, and
     * `AudioPipeline` already knows never to delete what this returns
     * (CONVENTIONS.md §8.3). When M0 decides, the work is to write the locator
     * and change the expression below — not to redesign anything above it.
     *
     * Until then it returns null, which is the FAIL-CLOSED answer. A
     * placeholder that captured everything by default would be the exact
     * failure this package exists to prevent, and it would be invisible: the
     * calls would simply arrive with audio nobody had authorised.
     */
    @Provides
    @Singleton
    fun oemRecordingLocator(): OemRecordingLocator =
        NoOpOemRecordingLocator("legacy28: raw-path locator lands in T71b")
}
