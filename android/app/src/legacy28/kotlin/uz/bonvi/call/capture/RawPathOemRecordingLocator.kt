package uz.bonvi.call.capture

import android.os.Environment
import timber.log.Timber
import uz.bonvi.call.domain.Decision
import java.io.File

/**
 * `legacy28`'s OEM harvest: plain files under the external-storage root (T71b).
 *
 * ═══ Why raw paths, and why this flavour ═══════════════════════════════════
 * An app whose `targetSdk` is 28 keeps the legacy view of external storage on
 * every Android version — the opt-out defaults to on below 29 — so
 * `Environment.getExternalStorageDirectory()` plus `File` reaches the folder
 * the handset's own recorder writes into. At `targetSdk` 29+ scoped storage
 * closes that door, which is what `modern34`'s MediaStore locator exists to
 * work around and why the two flavours exist at all (S1-RECORDING.md).
 *
 * It also reaches folders MediaStore cannot see: the Redmi this was written
 * against keeps a `.nomedia` next to `MIUI/sound_recorder`, which is precisely
 * an instruction to the media scanner to ignore everything below it.
 *
 * ⚠️ **Read-only, and narrow.** It lists only the folders in
 * [OemRecordingFolders.CANDIDATES], keeps only what
 * [OemRecordingMatch] accepts for THIS call, and never moves, renames,
 * copies or deletes anything. The files belong to the employee, and several of
 * them are recordings of calls this app is not allowed to look at.
 */
class RawPathOemRecordingLocator(
    private val root: File = Environment.getExternalStorageDirectory(),
) : OemRecordingLocator {

    override fun locate(capture: Decision.Capture): File? {
        val candidates = OemRecordingFolders.CANDIDATES
            .asSequence()
            .map { File(root, it) }
            .filter { it.isDirectory && it.canRead() }
            .flatMap { folder -> folder.listFiles()?.asSequence().orEmpty() }
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

        val picked = OemRecordingMatch.pick(candidates, capture)
        // The COUNT, never the names. A folder listing in a log line is the
        // employee's private call history, on a phone whose logs end up in
        // support chats (N26).
        Timber.i(
            "OEM harvest: %d candidate file(s) in range, %s",
            candidates.size,
            if (picked != null) "one matched" else "none matched",
        )
        return picked
    }

    override fun toString(): String = "RawPathOemRecordingLocator($root)"
}
