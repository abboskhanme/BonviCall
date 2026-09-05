package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * When audio may use cellular, and what is never retried (T74, N14, R14).
 */
class AudioUploadPolicyTest {

    private val now = 1_772_615_791_000L
    private fun hoursAgo(h: Long) = now - h * 60 * 60 * 1000L

    @Test
    fun `Wi-Fi always sends, immediately`() {
        assertThat(
            AudioUploadPolicy.decide(now, now, onWifi = true, onCellular = false, 0),
        ).isEqualTo(AudioUploadPolicy.Decision.SEND)
    }

    @Test
    fun `a fresh recording waits for Wi-Fi rather than spending cellular`() {
        assertThat(
            AudioUploadPolicy.decide(hoursAgo(2), now, onWifi = false, onCellular = true, 0),
        ).isEqualTo(AudioUploadPolicy.Decision.WAIT_FOR_WIFI)
    }

    @Test
    fun `after 24 hours it goes over cellular regardless`() {
        // A recording that never uploads because the phone is never on Wi-Fi is
        // a recording that does not exist — and the salesperson who is out all
        // day is exactly the one whose calls matter most.
        assertThat(
            AudioUploadPolicy.decide(hoursAgo(25), now, onWifi = false, onCellular = true, 0),
        ).isEqualTo(AudioUploadPolicy.Decision.SEND)
    }

    @Test
    fun `no network waits for a network, not for Wi-Fi`() {
        // Two different states: one resolves when any connection appears, the
        // other only when Wi-Fi does. Collapsing them makes a diagnostics
        // screen lie.
        assertThat(
            AudioUploadPolicy.decide(hoursAgo(48), now, onWifi = false, onCellular = false, 0),
        ).isEqualTo(AudioUploadPolicy.Decision.WAIT_FOR_NETWORK)
    }

    @Test
    fun `the monthly cap holds the recording, it never drops it`() {
        // N14's cap limits what the app COSTS, not what it keeps.
        val decision = AudioUploadPolicy.decide(
            hoursAgo(48), now, onWifi = false, onCellular = true,
            cellularBytesThisMonth = AudioUploadPolicy.MONTHLY_CELLULAR_CAP_BYTES,
        )
        assertThat(decision).isEqualTo(AudioUploadPolicy.Decision.HOLD_CAP_REACHED)
    }

    @Test
    fun `the cap does not block Wi-Fi`() {
        assertThat(
            AudioUploadPolicy.decide(
                hoursAgo(48), now, onWifi = true, onCellular = false,
                cellularBytesThisMonth = AudioUploadPolicy.MONTHLY_CELLULAR_CAP_BYTES * 2,
            ),
        ).isEqualTo(AudioUploadPolicy.Decision.SEND)
    }

    @Test
    fun `audio_not_attributable is permanent and deletes the local file`() {
        // The privacy boundary at the far end: the server could not match the
        // file to a registered-number call in its window, refused it, and wrote
        // no bytes. The window does not reopen, so retrying would spend the
        // employee's data in a loop on a file the server has already decided is
        // not the company's — and keeping it locally is worse than losing it.
        assertThat(AudioUploadPolicy.isPermanentFailure("audio_not_attributable")).isTrue()
        assertThat(AudioUploadPolicy.shouldDeleteLocalAudio("audio_not_attributable")).isTrue()
    }

    @Test
    fun `a transient failure is retried and keeps its file`() {
        assertThat(AudioUploadPolicy.isPermanentFailure("internal_error")).isFalse()
        assertThat(AudioUploadPolicy.isPermanentFailure("chunk_offset_mismatch")).isFalse()
        assertThat(AudioUploadPolicy.isPermanentFailure(null)).isFalse()
        assertThat(AudioUploadPolicy.shouldDeleteLocalAudio("internal_error")).isFalse()
    }

    @Test
    fun `a checksum mismatch stops retrying but keeps the file for diagnosis`() {
        assertThat(AudioUploadPolicy.isPermanentFailure("checksum_mismatch")).isTrue()
        assertThat(AudioUploadPolicy.shouldDeleteLocalAudio("checksum_mismatch")).isFalse()
    }

    @Test
    fun `the cap is 1 GB and the cellular deadline is 24 hours`() {
        assertThat(AudioUploadPolicy.MONTHLY_CELLULAR_CAP_BYTES).isEqualTo(1_073_741_824L)
        assertThat(AudioUploadPolicy.CELLULAR_AFTER_MS).isEqualTo(86_400_000L)
    }
}
