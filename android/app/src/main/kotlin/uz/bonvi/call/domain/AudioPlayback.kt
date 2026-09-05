package uz.bonvi.call.domain

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
 */
interface AudioPlayback {
    fun play(url: String)
    fun pause()

    /** A leaked player keeps a codec and, worse, keeps playing a colleague's
     *  conversation out loud. */
    fun release()
}
