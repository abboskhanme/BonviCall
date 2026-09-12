package uz.bonvi.call.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.OemRecordingLocator
import uz.bonvi.call.capture.RawPathOemRecordingLocator
import javax.inject.Singleton

/**
 * legacy28 — the ONE flavour-specific Kotlin source (SPEC §7.2).
 *
 * On targetSdk 28 the OEM recordings folder is reachable through
 * `Environment.getExternalStorageDirectory()` and plain `File` objects, so this
 * flavour binds the raw-path locator.
 */
@Module
@InstallIn(SingletonComponent::class)
object CaptureModule {

    /**
     * **T71b, landed 2026-09-11.** Was `NoOpOemRecordingLocator`, and the seam
     * around it was already finished — so this really was the one function the
     * task changed, exactly as the previous comment here promised.
     *
     * It was left as a stub until a real handset could say where these files
     * land. That handset arrived: a Redmi Note 14 on HyperOS, whose recorder
     * writes into `MIUI/sound_recorder/call_rec` with a `.nomedia` beside it.
     * [uz.bonvi.call.capture.OemRecordingFolders] carries that path and the
     * equivalent for every other manufacturer in the fleet.
     *
     * Still fail-closed: the locator returns null whenever nothing in the
     * call's own time window qualifies, and null remains `attribution_failed`.
     * What changed is that a file which DOES belong to this call is now found.
     */
    @Provides
    @Singleton
    fun oemRecordingLocator(): OemRecordingLocator = RawPathOemRecordingLocator()
}
