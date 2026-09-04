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

    @Provides
    @Singleton
    fun oemRecordingLocator(): OemRecordingLocator =
        NoOpOemRecordingLocator("modern34: the scoped-storage locator lands in T71b")
}
