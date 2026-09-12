package uz.bonvi.call.capture

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.domain.Decision

/**
 * The one pure function that decides which of the employee's files is THIS
 * call's recording. Its window arithmetic is a privacy boundary, and one
 * overflow in it silently disabled the preferred capture route on the first
 * real handset — so the arithmetic has its own tests now.
 */
class OemRecordingMatchTest {

    private fun proof(answeredAt: Long = 100_000L, endedAt: Long = 160_000L) = Decision.Capture(
        subscriptionId = 1,
        registeredNumber = "+998901112233",
        answeredAtEpochMillis = answeredAt,
        endedAtEpochMillis = endedAt,
    )

    private fun file(name: String, modifiedAt: Long, bytes: Long = 50_000L) =
        RecordingCandidate(handle = name, name = name, sizeBytes = bytes, lastModifiedMillis = modifiedAt)

    @Test
    fun `the window is five seconds before the answer to two minutes after the end`() {
        assertThat(OemRecordingMatch.windowFor(proof())).isEqualTo(95_000L..280_000L)
    }

    @Test
    fun `a live decision's provisional MAX end does not overflow the window shut`() {
        // A ringing call is evaluated with `endedAt = Long.MAX_VALUE`. Plain
        // addition of the post-buffer wraps negative and the range is empty:
        // every file, this call's own included, fails `in window`. That is
        // exactly what happened on 2026-09-12 -- 51 clean recordings in the
        // folder, zero matches, and the strategy reported attribution_failed
        // for every call.
        val window = OemRecordingMatch.windowFor(proof(endedAt = Long.MAX_VALUE))

        assertThat(window.isEmpty()).isFalse()
        assertThat(window.last).isEqualTo(Long.MAX_VALUE)
        assertThat(
            OemRecordingMatch.pick(
                listOf(file("call.mp3", modifiedAt = 165_000L)),
                proof(endedAt = Long.MAX_VALUE),
            ),
        ).isEqualTo("call.mp3")
    }

    @Test
    fun `the newest qualifying file wins and the rest are refused`() {
        val candidates = listOf(
            file("previous-call.mp3", modifiedAt = 90_000L), // before the window: the last call
            file("partial.mp3", modifiedAt = 150_000L),
            file("final.mp3", modifiedAt = 161_000L),
            file("stub.mp3", modifiedAt = 162_000L, bytes = 100L), // below MIN_FILE_BYTES
            file("notes.txt", modifiedAt = 163_000L), // not audio
        )

        assertThat(OemRecordingMatch.pick(candidates, proof())).isEqualTo("final.mp3")
    }
}
