package uz.bonvi.call.capture

import uz.bonvi.call.domain.Decision

/**
 * Where handsets put their own call recordings, and which file belongs to a
 * call (T71b).
 *
 * ═══ Why the rule lives here, away from the platform ═══════════════════════
 * The two locators reach the files very differently — `legacy28` walks raw
 * paths under the external-storage root, `modern34` queries MediaStore — but
 * the DECISION is the same in both, and it is the decision that can attach a
 * private conversation to a work call. So the platform half is per flavour and
 * this half is one pure function with tests, rather than the same arithmetic
 * written twice and drifting.
 *
 * ⚠️ **The filename is never parsed.** Every manufacturer names these
 * differently, several localise the name, and a phone set to a language nobody
 * anticipated would silently stop matching. Time, size and extension are
 * facts; a filename is a guess.
 */
object OemRecordingFolders {

    /**
     * Folders to look in, relative to the external-storage root, best first.
     *
     * Gathered per manufacturer rather than guessed: the Xiaomi path was read
     * off a live Redmi Note 14 running HyperOS (`MIUI/sound_recorder/call_rec`
     * exists there with a `.nomedia` beside it, which is also why MediaStore
     * alone cannot be trusted to see it). The rest follow the same shape each
     * vendor has used for years.
     *
     * A folder that does not exist costs one `isDirectory` call, so breadth is
     * cheap; missing a folder costs every recording on that handset.
     */
    val CANDIDATES: List<String> = listOf(
        // Xiaomi / Redmi / POCO — MIUI and HyperOS.
        "MIUI/sound_recorder/call_rec",
        "MIUI/sound_recorder/call_rec_auto",
        "Recordings/call_rec",

        // Samsung One UI.
        "Recordings/Call",
        "Sounds/Call",
        "Call",

        // Huawei / Honor — EMUI and MagicOS.
        "Sounds/CallRecord",
        "Recordings/CallRecord",
        "record/call",

        // Oppo / Realme / OnePlus — ColorOS and OxygenOS.
        "Recordings/PhoneRecord",
        "Music/Recordings/Call Recordings",
        "Record/PhoneRecord",

        // Vivo — Funtouch and OriginOS.
        "Record/Call",
        "记录/通话录音",

        // Generic and AOSP-ish builds.
        "CallRecordings",
        "Call Recordings",
        "PhoneRecord",
        "Recordings/Voice Recorder",
        "Recordings",
    )

    /**
     * Extensions a call recording can carry.
     *
     * `awb` and `opus` are here because AMR-WB and Opus both appear on newer
     * budget handsets, and a recording the app cannot name is a recording the
     * app throws away.
     */
    val AUDIO_EXTENSIONS: Set<String> = setOf(
        "m4a", "mp3", "amr", "awb", "wav", "3gp", "3gpp", "aac", "ogg", "opus", "mp4",
    )
}

/**
 * One thing the platform found, reduced to the four facts the rule needs.
 *
 * Generic in [handle] so a flavour can carry back whatever it must — a `File`
 * on `legacy28`, a content `Uri` on `modern34` — without this file importing
 * either.
 */
data class RecordingCandidate<T>(
    val handle: T,
    val name: String,
    val sizeBytes: Long,
    val lastModifiedMillis: Long,
)

/**
 * Which of the candidates, if any, is this call's recording.
 *
 * The rule is deliberately the one CallSentry arrived at and S1-RECORDING.md
 * measured, down to the buffer sizes — it is the only part of this product
 * where a competitor's field experience is directly transferable, and
 * inventing a different window would mean re-learning it on the client's
 * fleet.
 */
object OemRecordingMatch {

    /**
     * The window a file's `lastModified` must fall inside.
     *
     * **The pre-buffer is small on purpose (5 s).** A generous one reaches back
     * into the PREVIOUS call, whose file an OEM writer may have flushed late —
     * and attaching the previous conversation to this call is worse than
     * attaching nothing. The post-buffer is two minutes for exactly that
     * flush lateness on this call's own file.
     */
    fun windowFor(capture: Decision.Capture): LongRange =
        (capture.answeredAtEpochMillis - OemRecordingLocator.PRE_BUFFER_MS)..
            (capture.endedAtEpochMillis + OemRecordingLocator.POST_BUFFER_MS)

    /** Is this candidate eligible at all? */
    fun <T> matches(candidate: RecordingCandidate<T>, window: LongRange): Boolean {
        if (candidate.sizeBytes < OemRecordingLocator.MIN_FILE_BYTES) return false
        if (candidate.lastModifiedMillis !in window) return false
        val extension = candidate.name.substringAfterLast('.', "").lowercase()
        return extension in OemRecordingFolders.AUDIO_EXTENSIONS
    }

    /**
     * The call's recording, or null.
     *
     * Newest wins when several qualify: an OEM that keeps a partial file beside
     * the finished one writes the finished one last. Null is an ordinary
     * answer and becomes `attribution_failed` on the call, never a guess.
     */
    fun <T> pick(
        candidates: Iterable<RecordingCandidate<T>>,
        capture: Decision.Capture,
    ): T? {
        val window = windowFor(capture)
        return candidates
            .filter { matches(it, window) }
            .maxByOrNull { it.lastModifiedMillis }
            ?.handle
    }
}
