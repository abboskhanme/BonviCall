package uz.bonvi.call.data.player

import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.common.Player
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.AudioPlayback
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Plays one of the employee's own recordings (N43, client request).
 *
 * ═══ Why an OkHttp data source and not the default ═════════════════════════
 * The audio endpoint requires an `Authorization` header and answers `Range`
 * with **206 + `Content-Range`**. ExoPlayer's default HTTP source cannot attach
 * the header, and a `fetch`-then-play approach would download a twenty-minute
 * recording before the first second of sound — over cellular, from a personal
 * data allowance (R14).
 *
 * Routing it through the app's own [OkHttpClient] solves both: the auth
 * interceptor attaches the token, ExoPlayer issues its own range requests, and
 * **seek is native** — dragging to 15:00 fetches from 15:00 rather than from
 * zero. The panel needed a Service Worker to achieve the same thing in a
 * browser; on Android it is one data-source factory.
 *
 * The base-URL interceptor is on this client too, which is correct here: the
 * URL is built from the same configured host, so a rewrite is a no-op, and a
 * phone repointed at a test server plays that server's audio rather than
 * production's.
 */
/**
 * `@UnstableApi` on the class rather than a project-wide opt-in.
 *
 * `OkHttpDataSource` and `DefaultMediaSourceFactory` are Media3's unstable
 * surface. Marking the one class that touches them keeps the opt-in visible
 * where the risk is — a library upgrade breaking this file is a compile error
 * here, not a silent behaviour change somewhere else.
 */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
@Singleton
class Media3AudioPlayback @Inject constructor(
    @ApplicationContext private val context: Context,
    private val client: OkHttpClient,
    private val session: SessionStore,
) : AudioPlayback {

    private var player: ExoPlayer? = null

    /** ExoPlayer is single-threaded and wants the main looper; the poll that
     *  reads its position therefore runs there too. */
    private val scope = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())
    private var ticker: Job? = null

    private val _progress = MutableStateFlow(AudioPlayback.Progress())
    override val progress: StateFlow<AudioPlayback.Progress> = _progress.asStateFlow()

    /** Created lazily: an ExoPlayer instance holds a codec, and holding one for
     *  a screen the employee may never open is a codec another app cannot use. */
    fun acquire(): ExoPlayer = player ?: build().also { player = it }

    private fun build(): ExoPlayer {
        val factory = OkHttpDataSource.Factory(client)
            .setDefaultRequestProperties(
                // Belt and braces: the interceptor sets this too, but a data
                // source that silently sent no token would fail as a 401 in the
                // middle of playback rather than at the start, which reads as a
                // corrupt file.
                buildMap {
                    session.snapshot.accessToken?.let { put("Authorization", "Bearer $it") }
                },
            )
        return ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(factory))
            .build()
    }

    override fun play(callId: String, url: String) {
        acquire().apply {
            setMediaItem(MediaItem.fromUri(url))
            prepare()
            playWhenReady = true
        }
        _progress.value = AudioPlayback.Progress(callId = callId, playing = true)
        startTicking()
    }

    override fun pause() {
        player?.playWhenReady = false
        _progress.value = _progress.value.copy(playing = false)
    }

    override fun resume() {
        val active = player ?: return
        // A recording played to its end sits at the end: pressing play there
        // must start it again rather than do nothing, which is what an
        // untouched `playWhenReady = true` would look like.
        if (active.playbackState == Player.STATE_ENDED) active.seekTo(0)
        active.playWhenReady = true
        _progress.value = _progress.value.copy(playing = true)
        startTicking()
    }

    override fun seekTo(positionMs: Long) {
        val active = player ?: return
        active.seekTo(positionMs.coerceAtLeast(0))
        // Published immediately rather than at the next tick: a slider that
        // snaps back for 200 ms before landing reads as a control that did not
        // take.
        _progress.value = _progress.value.copy(positionMs = active.currentPosition)
    }

    override fun stop() {
        ticker?.cancel()
        ticker = null
        player?.run {
            playWhenReady = false
            stop()
            clearMediaItems()
        }
        _progress.value = AudioPlayback.Progress()
    }

    /** Called when the screen goes away. A leaked player keeps a codec and,
     *  worse, keeps playing a colleague's conversation out loud. */
    override fun release() {
        ticker?.cancel()
        ticker = null
        player?.release()
        player = null
        _progress.value = AudioPlayback.Progress()
    }

    /**
     * ExoPlayer reports state changes, never a moving position, so the clock
     * the screen draws has to be polled.
     *
     * Every 200 ms: fast enough that the thumb moves smoothly, slow enough to
     * cost nothing on a phone whose battery belongs to the employee (N13). It
     * runs only while a recording is loaded and stops itself at the end, so a
     * screen left open does not hold a timer for a player that is finished.
     */
    private fun startTicking() {
        if (ticker?.isActive == true) return
        ticker = scope.launch {
            while (isActive) {
                val active = player ?: break
                val ended = active.playbackState == Player.STATE_ENDED
                _progress.value = _progress.value.copy(
                    positionMs = active.currentPosition.coerceAtLeast(0),
                    // `duration` is C.TIME_UNSET until the container is read.
                    durationMs = active.duration.takeIf { it > 0 } ?: 0,
                    playing = active.playWhenReady && !ended,
                )
                if (ended) {
                    // Stay on the row with the recording at its end: the
                    // employee can press play to hear it again, and the time
                    // they just listened to is still on screen.
                    _progress.value = _progress.value.copy(playing = false)
                    break
                }
                delay(TICK_MS)
            }
            ticker = null
        }
    }

    private companion object {
        const val TICK_MS = 200L
    }
}
