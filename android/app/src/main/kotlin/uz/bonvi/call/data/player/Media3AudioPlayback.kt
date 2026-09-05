package uz.bonvi.call.data.player

import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import dagger.hilt.android.qualifiers.ApplicationContext
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

    override fun play(url: String) {
        acquire().apply {
            setMediaItem(MediaItem.fromUri(url))
            prepare()
            playWhenReady = true
        }
    }

    override fun pause() {
        player?.playWhenReady = false
    }

    /** Called when the screen goes away. A leaked player keeps a codec and,
     *  worse, keeps playing a colleague's conversation out loud. */
    override fun release() {
        player?.release()
        player = null
    }
}
