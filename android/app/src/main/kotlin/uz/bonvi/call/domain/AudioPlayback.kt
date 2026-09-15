package uz.bonvi.call.domain

import kotlinx.coroutines.flow.StateFlow

/**
 * Plays one of the employee's own recordings.
 *
 * An interface in `domain/` because `ui/` may not reach `data/remote` or an
 * HTTP client directly (SPEC §7.1) — "the one layering rule worth enforcing
 * without a module system, because it is the one that decides whether the
 * screens can be tested without a phone". `ArchitectureRulesTest` caught the
 * first version of the player sitting in `ui/` with an OkHttp import, which is
 * exactly what the rule is for.
 *
 * The implementation is `data/player/Media3AudioPlayback`, which streams
 * through the app's own OkHttp client so the token rides along and ExoPlayer
 * issues real `Range` requests (N43).
 *
 * ═══ Why this interface carries POSITION ═══════════════════════════════════
 * It used to be `play` / `pause` / `release`, and the screen was a single
 * button that swapped its own label. Sound came out, and that was all anybody
 * could tell: not how long the recording is, not where in it the playback is,
 * not whether it had finished. An employee checking "what did I say at the
 * end" had to listen to the whole call to reach the end.
 *
 * So the player publishes [Progress] and takes [seekTo]. Position is polled
 * rather than pushed because that is what ExoPlayer offers — it reports state
 * changes, never a continuous position — and the poll lives in the
 * implementation so that every screen reads the same clock.
 */
interface AudioPlayback {

    /** Where the current recording is, for the screen to draw. */
    data class Progress(
        /** The `id` passed to [play], or null when nothing is loaded. */
        val callId: String? = null,
        val positionMs: Long = 0,
        /** `0` until ExoPlayer has read the container's duration. */
        val durationMs: Long = 0,
        val playing: Boolean = false,
    ) {
        /** 0f..1f, and never NaN for a duration that is not known yet. */
        val fraction: Float
            get() = if (durationMs <= 0) 0f else (positionMs.toFloat() / durationMs).coerceIn(0f, 1f)
    }

    val progress: StateFlow<Progress>

    /**
     * Start [url], remembering [callId] so a list can tell which row is
     * sounding. Playing a second recording replaces the first — one codec,
     * and two conversations out loud at once is nobody's intention.
     */
    fun play(callId: String, url: String)

    /** Keep the position, stop the sound. [resume] continues from there. */
    fun pause()

    fun resume()

    fun seekTo(positionMs: Long)

    /** Forget the recording entirely: the row loses its player. */
    fun stop()

    /** A leaked player keeps a codec and, worse, keeps playing a colleague's
     *  conversation out loud. */
    fun release()
}
