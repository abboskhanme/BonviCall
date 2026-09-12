package uz.bonvi.call.capture

import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import timber.log.Timber
import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * `modern34`'s OEM harvest (T71b).
 *
 * ═══ Two routes, because neither is sufficient alone ═══════════════════════
 * Under scoped storage an app cannot simply list another app's folder, so the
 * first route is **MediaStore**: ask for audio whose `DATE_MODIFIED` falls in
 * this call's window and whose path looks like a call-recording folder.
 *
 * That is not enough on its own. Several manufacturers — Xiaomi among them,
 * measured on the Redmi Note 14 this was written against — drop a `.nomedia`
 * beside the recorder's directory, which tells the media scanner to index
 * nothing below it. Those files exist and MediaStore will never mention them.
 * So the second route is a direct read of the same folders, which
 * **All-files access** (`MANAGE_EXTERNAL_STORAGE`, the alarming permission E2
 * asks for on this flavour) makes legal.
 *
 * If the agent declined All-files access the second route simply finds
 * nothing, which is the honest outcome: the call ships with
 * `attribution_failed` rather than with somebody else's audio.
 *
 * ⚠️ Read-only, and narrow: only the folders in
 * [OemRecordingFolders.CANDIDATES], only what [OemRecordingMatch] accepts for
 * THIS call, and nothing is ever moved, renamed or deleted.
 */
class MediaStoreOemRecordingLocator(
    private val context: Context,
    private val root: File = Environment.getExternalStorageDirectory(),
) : OemRecordingLocator {

    override fun locate(capture: Decision.Capture): File? {
        val candidates = queryMediaStore(capture) + scanFolders()
        val picked = OemRecordingMatch.pick(candidates, capture)
        Timber.i(
            "OEM harvest (modern34): %d candidate file(s), %s",
            candidates.size,
            if (picked != null) "one matched" else "none matched",
        )
        return picked
    }

    /**
     * Route 1: what the media scanner has indexed.
     *
     * The window is applied in SQL as well as in [OemRecordingMatch] — not
     * belt and braces, but a much smaller cursor: on a phone with a few
     * thousand audio files, filtering afterwards means reading them all.
     * `DATE_MODIFIED` is in **seconds**.
     */
    private fun queryMediaStore(capture: Decision.Capture): List<RecordingCandidate<File>> {
        val window = OemRecordingMatch.windowFor(capture)
        val projection = arrayOf(
            MediaStore.Audio.Media.DATA,
            MediaStore.Audio.Media.DISPLAY_NAME,
            MediaStore.Audio.Media.SIZE,
            MediaStore.Audio.Media.DATE_MODIFIED,
        )
        val selection =
            "${MediaStore.Audio.Media.DATE_MODIFIED} >= ? AND " +
                "${MediaStore.Audio.Media.DATE_MODIFIED} <= ? AND " +
                "${MediaStore.Audio.Media.SIZE} >= ?"
        val args = arrayOf(
            (window.first / 1_000).toString(),
            (window.last / 1_000).toString(),
            OemRecordingLocator.MIN_FILE_BYTES.toString(),
        )

        @Suppress("TooGenericExceptionCaught")
        return try {
            context.contentResolver.query(
                MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                args,
                null,
            ).use { cursor ->
                if (cursor == null) return emptyList()
                val pathColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.DATA)
                val nameColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.DISPLAY_NAME)
                val sizeColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.SIZE)
                val dateColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.DATE_MODIFIED)
                buildList {
                    while (cursor.moveToNext()) {
                        val path = cursor.getString(pathColumn) ?: continue
                        // The folder test is what keeps this from reaching the
                        // employee's music and voice memos.
                        if (!looksLikeCallRecordingPath(path)) continue
                        add(
                            RecordingCandidate(
                                handle = File(path),
                                name = cursor.getString(nameColumn) ?: File(path).name,
                                sizeBytes = cursor.getLong(sizeColumn),
                                lastModifiedMillis = cursor.getLong(dateColumn) * 1_000L,
                            ),
                        )
                    }
                }
            }
        } catch (error: Exception) {
            // A refused query is a phone without the permission, or an OEM
            // with a non-standard provider. Neither is a reason to fail the
            // call: route 2 may still find it, and null is a supported answer.
            Timber.w(error, "MediaStore audio query refused")
            emptyList()
        }
    }

    /**
     * Route 2: read the folders directly.
     *
     * Legal only with All-files access, and the only way to reach a folder the
     * manufacturer has hidden from the scanner with `.nomedia`.
     */
    private fun scanFolders(): List<RecordingCandidate<File>> {
        @Suppress("TooGenericExceptionCaught")
        return try {
            OemRecordingFolders.CANDIDATES
                .asSequence()
                .map { File(root, it) }
                .filter { it.isDirectory && it.canRead() }
                .flatMap { it.listFiles()?.asSequence().orEmpty() }
                .filter { it.isFile }
                .map {
                    RecordingCandidate(
                        handle = it,
                        name = it.name,
                        sizeBytes = it.length(),
                        lastModifiedMillis = it.lastModified(),
                    )
                }
                .toList()
        } catch (error: Exception) {
            Timber.w(error, "Direct folder scan refused; All-files access is probably not granted")
            emptyList()
        }
    }

    /** Does this absolute path sit in one of the folders we harvest? */
    private fun looksLikeCallRecordingPath(path: String): Boolean {
        val normalised = path.replace('\\', '/').lowercase()
        return OemRecordingFolders.CANDIDATES.any { candidate ->
            normalised.contains("/${candidate.lowercase()}/")
        }
    }

    override fun toString(): String = "MediaStoreOemRecordingLocator"
}
