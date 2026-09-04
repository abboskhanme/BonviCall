package uz.bonvi.call.capture

import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.annotation.RequiresApi
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.core.Capabilities
import uz.bonvi.call.enrolment.StorageAccessProbe
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Can this build reach the OEM recordings folder? (SPEC §7.8, "variant-specific")
 *
 * The two answers differ, and the difference is asked as a **capability**, not
 * as a version and not as a flavour: `Capabilities.requiresAllFilesAccess()`.
 * That is why this is one class in `main` rather than two in the flavour source
 * sets — SPEC §7.2 keeps the flavour-specific surface to `di/CaptureModule.kt`
 * and the two manifests, and a probe that branched on the flavour would be a
 * third place the two builds could silently diverge.
 *
 * It lives under `capture/` because it touches `Environment` and `MediaStore`
 * (SPEC §7.1, `ArchitectureRulesTest`). It only ever ASKS — nothing here opens,
 * moves, modifies or deletes a file, and the actual harvest is T71b behind the
 * privacy boundary.
 */
@Singleton
class OemFolderStorageAccessProbe @Inject constructor(
    @ApplicationContext private val context: Context,
) : StorageAccessProbe {

    override fun hasAccess(): Boolean =
        if (Capabilities.requiresAllFilesAccess()) hasAllFilesAccess() else canReadLegacyFolder()

    // `Capabilities.requiresAllFilesAccess()` is annotated @ChecksSdkIntAtLeast,
    // so lint understands these branches are API-guarded without a raw SDK_INT
    // appearing outside core/Capabilities.kt.

    override fun describe(): String =
        if (Capabilities.requiresAllFilesAccess()) {
            if (hasAllFilesAccess()) "all-files access granted" else "all-files access not granted"
        } else {
            if (canReadLegacyFolder()) {
                "recordings folder readable"
            } else {
                "no readable recordings folder"
            }
        }

    /**
     * `@RequiresApi`, not `@SuppressLint`.
     *
     * Lint understands `Capabilities.requiresAllFilesAccess()` as a version
     * guard at the CALL SITE (it is `@ChecksSdkIntAtLeast`), but it analyses
     * this function's body independently. The annotation says what the guard
     * already guarantees, and it keeps the raw `SDK_INT` inside
     * core/Capabilities.kt where the architecture rule requires it.
     */
    @RequiresApi(Build.VERSION_CODES.R)
    private fun hasAllFilesAccess(): Boolean =
        @Suppress("TooGenericExceptionCaught")
        try {
            Environment.isExternalStorageManager()
        } catch (error: Exception) {
            // Broad, and the specific failure is an OEM that removed the API on
            // a build where it should exist. "We cannot tell" is not "granted".
            Timber.w(error, "isExternalStorageManager unavailable")
            false
        }

    /**
     * Legacy path: is any of the folders S1 found actually readable?
     *
     * Existence is not enough — a folder that lists nothing because the OS is
     * refusing looks identical to an empty one, and that is the same
     * `granted_not_working` trap as everywhere else in this flow.
     */
    private fun canReadLegacyFolder(): Boolean =
        @Suppress("TooGenericExceptionCaught")
        try {
            @Suppress("DEPRECATION")
            val root = Environment.getExternalStorageDirectory()
            CANDIDATE_FOLDERS.any { relative ->
                java.io.File(root, relative).let { it.isDirectory && it.canRead() }
            }
        } catch (error: Exception) {
            Timber.w(error, "Could not test the recordings folder")
            false
        }

    /** Whether the media store can answer at all. Used only by the modern
     *  route's `describe()`; the harvest itself is T71b. */
    @Suppress("unused")
    private fun mediaStoreAnswers(): Boolean =
        @Suppress("TooGenericExceptionCaught")
        try {
            context.contentResolver.query(
                MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
                arrayOf(MediaStore.Audio.Media._ID),
                null,
                null,
                null,
            ).use { it != null }
        } catch (error: Exception) {
            Timber.w(error, "MediaStore audio query refused")
            false
        }

    private companion object {
        /** The preference order S1 found in the prototype. Read-only, and only
         *  ever tested for readability here. */
        val CANDIDATE_FOLDERS = listOf(
            "Recordings/Call",
            "Recordings/Voice Recorder",
            "Call",
            "Sounds/Call",
            "CallRecordings",
        )
    }
}
