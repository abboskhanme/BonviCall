package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The number the progress bar is drawn from.
 *
 * It is one division, and every way it can go wrong puts a visible fault on
 * the screen: a NaN width crashes the slider, a fraction above 1 draws a thumb
 * outside its track, and a duration of zero — which is what ExoPlayer reports
 * until it has read the container — is the normal state for the first frames
 * of every recording.
 */
class AudioPlaybackProgressTest {

    @Test
    fun `an unread duration is nought and not NaN`() {
        val progress = AudioPlayback.Progress(callId = "c1", positionMs = 0, durationMs = 0)

        assertThat(progress.fraction).isEqualTo(0f)
        assertThat(progress.fraction.isNaN()).isFalse()
    }

    @Test
    fun `half way through is a half`() {
        val progress = AudioPlayback.Progress(positionMs = 30_000, durationMs = 60_000)

        assertThat(progress.fraction).isWithin(0.001f).of(0.5f)
    }

    @Test
    fun `a position past the end stays on the track`() {
        // ExoPlayer can report a position a few milliseconds past the duration
        // at the end of a stream; a slider given 1.02 draws its thumb outside.
        val progress = AudioPlayback.Progress(positionMs = 61_000, durationMs = 60_000)

        assertThat(progress.fraction).isEqualTo(1f)
    }

    @Test
    fun `nothing loaded is nothing playing`() {
        val idle = AudioPlayback.Progress()

        assertThat(idle.callId).isNull()
        assertThat(idle.playing).isFalse()
        assertThat(idle.fraction).isEqualTo(0f)
    }
}
