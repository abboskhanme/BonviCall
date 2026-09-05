package uz.bonvi.call.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.NoOpOemRecordingLocator
import uz.bonvi.call.capture.OemRecordingLocator
import javax.inject.Singleton

/**
 * modern34 — the ONE flavour-specific Kotlin source (SPEC §7.2).
 *
 * Under scoped storage the same files are reached through `MediaStore` plus
 * All-files access, so this flavour binds the MediaStore locator. The window,
 * the size floor and the read-only rule are identical: the boundary does not
 * change with the storage API, only the way the folder is opened.
 *
 * TODO(T71b): bind `MediaStoreOemRecordingLocator`, querying
 * `MediaStore.Audio` filtered on `DATE_MODIFIED` inside the call window.
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
        NoOpOemRecordingLocator("modern34: the scoped-storage locator lands in T71b")
}
