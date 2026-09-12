package uz.bonvi.call.di

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.capture.MediaStoreOemRecordingLocator
import uz.bonvi.call.capture.OemRecordingLocator
import javax.inject.Singleton

/**
 * modern34 — the ONE flavour-specific Kotlin source (SPEC §7.2).
 *
 * Under scoped storage the same files are reached through `MediaStore` plus
 * All-files access. The window, the size floor and the read-only rule are
 * identical: the boundary does not change with the storage API, only the way
 * the folder is opened.
 */
@Module
@InstallIn(SingletonComponent::class)
object CaptureModule {

    /**
     * **T71b, landed 2026-09-11.** See the `legacy28` twin for the history.
     *
     * This flavour has the harder job of the two and is the weaker of them:
     * a manufacturer that hides its recorder folder from the media scanner —
     * Xiaomi does, with a `.nomedia` — is invisible to MediaStore, so the
     * locator also reads the folders directly, which is legal only while
     * All-files access is granted. An agent who declined that permission gets
     * calls with `attribution_failed` rather than somebody else's audio, which
     * is the correct trade and the reason `legacy28` exists at all.
     */
    @Provides
    @Singleton
    fun oemRecordingLocator(
        @ApplicationContext context: Context,
    ): OemRecordingLocator = MediaStoreOemRecordingLocator(context)
}
