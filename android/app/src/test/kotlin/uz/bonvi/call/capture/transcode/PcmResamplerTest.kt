package uz.bonvi.call.capture.transcode

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin

/**
 * The resampler the OEM route depends on.
 *
 * The first harvested recording reached the server three times too long and
 * an octave and a half too low (2026-09-12): 48 kHz in, "16 kHz" out, no
 * conversion between. These pin the arithmetic so it cannot happen again.
 */
class PcmResamplerTest {

    private fun pcm(samples: ShortArray, channels: Int = 1): ByteBuffer =
        ByteBuffer.allocate(samples.size * 2).order(ByteOrder.nativeOrder()).also { buffer ->
            samples.forEach { buffer.putShort(it) }
            buffer.flip()
        }.also { check(samples.size % channels == 0) }

    private fun shorts(buffer: ByteBuffer): ShortArray {
        val view = buffer.duplicate().order(ByteOrder.nativeOrder())
        return ShortArray(view.remaining() / 2) { view.getShort(buffer.position() + it * 2) }
    }

    @Test
    fun `one second at 48 kHz becomes one second at 16 kHz, across buffer edges`() {
        // A 440 Hz tone, delivered in the uneven chunks a decoder produces.
        val source = ShortArray(48_000) { (sin(2 * PI * 440 * it / 48_000.0) * 10_000).toInt().toShort() }
        val resampler = PcmResampler(sourceRateHz = 48_000, sourceChannels = 1, targetRateHz = 16_000)

        val output = mutableListOf<Short>()
        var cursor = 0
        for (chunk in listOf(1_152, 4_096, 7, 20_000, 22_745)) {
            val slice = source.copyOfRange(cursor, cursor + chunk)
            output += shorts(resampler.convert(pcm(slice), 0, slice.size * 2)).toList()
            cursor += chunk
        }

        // 16 000 samples, give or take the edge that has no right-hand neighbour yet.
        assertThat(output.size).isAtLeast(15_998)
        assertThat(output.size).isAtMost(16_000)
        // And they are the SAME tone: sample n of the output is the source at 3n.
        val worst = output.indices.maxOf { abs(output[it] - source[it * 3]) }
        assertThat(worst).isLessThan(60) // linear interpolation of a 440 Hz tone at 48 kHz
    }

    @Test
    fun `stereo is averaged to mono`() {
        val resampler = PcmResampler(sourceRateHz = 16_000, sourceChannels = 2, targetRateHz = 16_000)
        val interleaved = ShortArray(8) { if (it % 2 == 0) 1_000 else 3_000 } // L=1000, R=3000

        val out = shorts(resampler.convert(pcm(interleaved, channels = 2), 0, interleaved.size * 2))

        assertThat(out.toList()).containsExactly(2_000.toShort(), 2_000.toShort(), 2_000.toShort())
        // The fourth frame is carried into the next buffer, where it becomes
        // the left neighbour of the next sample.
        assertThat(shorts(resampler.convert(pcm(shortArrayOf(2_000, 2_000)), 0, 4)).toList())
            .containsExactly(2_000.toShort())
    }

    @Test
    fun `16 kHz mono passes through untouched`() {
        val resampler = PcmResampler(sourceRateHz = 16_000, sourceChannels = 1, targetRateHz = 16_000)
        val samples = shortArrayOf(1, -2, 3, -4)

        val out = resampler.convert(pcm(samples), 0, 8)

        assertThat(resampler.passThrough).isTrue()
        assertThat(shorts(out).toList()).containsExactly(1.toShort(), (-2).toShort(), 3.toShort(), (-4).toShort())
    }

    @Test
    fun `an offset into the decoder buffer is honoured`() {
        val resampler = PcmResampler(sourceRateHz = 32_000, sourceChannels = 1, targetRateHz = 16_000)
        val samples = shortArrayOf(9_999, 9_999, 0, 100, 200, 300, 400, 500)

        // Skip the first two samples (4 bytes).
        val out = shorts(resampler.convert(pcm(samples), 4, 12))

        assertThat(out.toList()).containsExactly(0.toShort(), 200.toShort(), 400.toShort())
    }
}
