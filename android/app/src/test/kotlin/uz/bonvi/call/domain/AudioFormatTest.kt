package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * The upload format (T73, N17, N18, N21, R14).
 *
 * These constants are the difference between ~10.8 MB and ~54 MB per hour of
 * speech. At ~15 000 calls a month the second number is about **6 GB per agent
 * per month of mobile data, from a personal phone's plan** — which is how the
 * app gets uninstalled for a reason nobody reports.
 */
class AudioFormatTest {

    @Test
    fun `mono 16 kHz 24 kbps, which is N17's number`() {
        assertThat(AudioFormat.CHANNELS).isEqualTo(1)
        assertThat(AudioFormat.SAMPLE_RATE_HZ).isEqualTo(16_000)
        assertThat(AudioFormat.BITRATE_BPS).isAtMost(24_000)
    }

    @Test
    fun `an hour of speech is about 10_8 MB`() {
        // N18's storage projection and N14's data cap are both computed from
        // this number, so it is asserted rather than assumed.
        assertThat(AudioFormat.BYTES_PER_HOUR).isEqualTo(10_800_000L)
        assertThat(AudioFormat.BYTES_PER_HOUR).isLessThan(11L * 1024 * 1024)
    }

    @Test
    fun `the sample rate is not below what ASR needs`() {
        // N21: the audio must survive being fed to speech-to-text later without
        // a second lossy transcode. 16 kHz is ASR's native input rate —
        // resampling down to it is free, starting below it cannot be undone.
        assertThat(AudioFormat.SAMPLE_RATE_HZ).isAtLeast(16_000)
    }

    @Test
    fun `both targets exist and both are in the wire contract`() {
        // SPEC §7.6: MediaMuxer only gained Ogg output at API 29 and legacy28
        // must run on 26-28 — the variant S1 says captures both voices, so it
        // cannot simply be dropped. The fallback is counted, not hidden.
        assertThat(AudioFormat.Target.entries.map { it.codec })
            .containsExactly("opus", "aac_lc")
        assertThat(AudioFormat.Target.entries.map { it.container })
            .containsExactly("ogg", "mp4")
    }

    @Test
    fun `every transcode failure maps to a reason the gap report can group by`() {
        // A transcode failure must never be the reason a call is LOST: the call
        // ships with an honest reason from the closed enum (UC-14, T75).
        for (failure in TranscodeFailure.entries) {
            assertThat(AudioMissingReason.entries).contains(failure.reason)
        }
    }

    @Test
    fun `a failed transcode is never reported as pending_upload`() {
        // pending_upload is excluded from the gap report's denominator. A
        // failure hidden behind it would make a broken fleet look healthy.
        for (failure in TranscodeFailure.entries) {
            assertThat(failure.reason).isNotEqualTo(AudioMissingReason.PENDING_UPLOAD)
            assertThat(failure.reason).isNotEqualTo(AudioMissingReason.NOT_EXPECTED)
        }
    }
}
