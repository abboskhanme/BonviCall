package uz.bonvi.call.service

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.DeviceAuthState
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Revocation (T84, UC-08).
 *
 * ═══ The state this exists to prevent ══════════════════════════════════════
 * **A revoked phone still carrying recordings of an employee's calls is the
 * worst state this product can be in, and it is the one nobody would ever look
 * for.** The panel says the device is revoked; the handset says nothing; the
 * audio sits in app-private storage until the app is uninstalled, which may be
 * never. Every other failure in this product is a missing call. This one is the
 * opposite, and it is on somebody's personal phone.
 *
 * So revocation does three things, in this order:
 *
 * 1. **Stop capturing.** The auth state flips to `REVOKED`, whose `canCapture`
 *    is false, so the detector's boundary rejects everything from then on.
 * 2. **Delete all local audio** — uploaded or not. UC-08 says "then confirms",
 *    and the confirmation is worth nothing if the deletion is conditional on a
 *    successful upload that may never happen.
 * 3. **Keep the metadata queue** until the server has it. A revoke that raced
 *    an upload must not silently lose the last few calls, and call metadata
 *    carries no conversation — 30 days of it is under 2 MB.
 *
 * Point 2 and point 3 look inconsistent and are not: the audio is the sensitive
 * artefact and the metadata is the audit trail. Deleting the first protects the
 * employee; keeping the second protects the record of what was captured before
 * the revoke.
 */
@Singleton
class Revocation @Inject constructor(
    @ApplicationContext private val context: Context,
    private val session: SessionStore,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    data class Result(val deletedFiles: Int, val deletedBytes: Long)

    suspend fun revokeLocally(): Result = withContext(io) {
        // 1. Stop capturing FIRST. If the deletion is interrupted, a phone that
        // has stopped capturing and still holds files is recoverable; one that
        // deleted its files and kept capturing is not.
        session.saveAuthState(DeviceAuthState.REVOKED.wire)

        // 2. Everything, uploaded or not.
        val result = deleteAllAudio()
        Timber.w(
            "Installation revoked: deleted %d audio file(s), %d bytes",
            result.deletedFiles, result.deletedBytes,
        )

        // 3. The metadata queue is deliberately untouched — see the class
        // docstring. It drains, or it is lost with the app; either way it
        // contains no conversation.
        result
    }

    /**
     * Every recording this app made or transcoded.
     *
     * Only app-private storage is touched. An **OEM-harvested file is never
     * deleted** even here: it is the employee's own recording in their own
     * folder, and it was only ever opened read-only (CONVENTIONS.md §8.3).
     * Revoking the company's access to a phone does not give the company
     * licence to delete the owner's files.
     */
    private fun deleteAllAudio(): Result {
        var files = 0
        var bytes = 0L
        for (directory in audioDirectories()) {
            if (!directory.isDirectory) continue
            directory.walkBottomUp().forEach { file ->
                if (file.isFile && file.extension in AUDIO_EXTENSIONS) {
                    bytes += file.length()
                    if (file.delete()) files++
                }
            }
        }
        return Result(files, bytes)
    }

    fun audioDirectories(): List<File> = listOf(
        File(context.filesDir, AUDIO_DIR),
        File(context.cacheDir, AUDIO_DIR),
    )

    private companion object {
        const val AUDIO_DIR = "audio"

        /** The formats this app produces (SPEC §7.6) plus the recorder's raw
         *  output. Extension-scoped rather than "delete the directory" so a
         *  future non-audio file in the same folder is not destroyed silently. */
        val AUDIO_EXTENSIONS = setOf("ogg", "m4a", "mp4", "aac", "wav", "amr")
    }
}
