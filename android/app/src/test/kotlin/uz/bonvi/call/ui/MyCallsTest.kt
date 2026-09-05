package uz.bonvi.call.ui

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.AudioState
import uz.bonvi.call.domain.CallDirection
import uz.bonvi.call.domain.CallDisposition
import uz.bonvi.call.domain.MyCall
import uz.bonvi.call.TestPaths

/**
 * The employee's own calls (client request, N41).
 *
 * The two rules that decide whether the screen is trustworthy: a play control
 * appears **only** where the audio actually exists, and `audio_state` is
 * **copied from the server, never re-derived** from the row.
 */
class MyCallsTest {

    private fun call(
        state: AudioState,
        reason: AudioMissingReason? = null,
    ) = MyCall(
        id = "1",
        clientCallId = "c1",
        direction = CallDirection.OUTGOING,
        disposition = CallDisposition.ANSWERED,
        remoteNumber = "901112233",
        contactName = null,
        startedAtEpochMillis = 1_772_615_791_000L,
        durationSec = 60,
        audioState = state,
        audioMissingReason = reason,
        captureRoute = null,
    )

    @Test
    fun `only a recorded call is playable`() {
        // A button that answers 410 teaches somebody the app is broken when it
        // is behaving exactly as designed.
        assertThat(call(AudioState.RECORDED).playable).isTrue()
        for (state in AudioState.entries - AudioState.RECORDED) {
            assertThat(call(state).playable).isFalse()
        }
    }

    @Test
    fun `expired is not a failure`() {
        // The recording existed and retention removed it — the system working.
        // It carries no reason, because there is nothing that went wrong.
        val expired = call(AudioState.EXPIRED)
        assertThat(expired.audioMissingReason).isNull()
        assertThat(expired.playable).isFalse()
    }

    @Test
    fun `every audio state has a wire value the server can send`() {
        assertThat(AudioState.entries.map { it.wire })
            .containsExactly("recorded", "expired", "queued", "not_expected", "missing")
    }

    @Test
    fun `an unknown state falls back to missing rather than crashing`() {
        // A newer server must not take down a fleet we cannot force-update.
        assertThat(AudioState.fromWire("something_new")).isEqualTo(AudioState.MISSING)
    }

    @Test
    fun `audio_state is copied from the server, never derived here`() {
        // It needs call_audio.deleted_at, which the call row does not carry. A
        // client deriving it from has_audio would offer a play button for a
        // recording retention has already removed.
        val gateway = TestPaths.kotlinSources()
            .single { it.name == "RetrofitMyCallsGateway.kt" }.readText()
        assertThat(gateway).contains("audioState = AudioState.fromWire(audioState.value)")
        assertThat(gateway).doesNotContain("if (hasAudio)")
    }

    @Test
    fun `nothing filters the list client-side`() {
        // The narrowing to this agent is the SERVER's, by agent_id — scoping by
        // installation_id looks equally correct and would silently empty an
        // employee's history the day they got a replacement handset (SPEC §9.3).
        val gateway = TestPaths.kotlinSources()
            .single { it.name == "RetrofitMyCallsGateway.kt" }.readText()
        for (leak in listOf(".filter {", ".filterNot {", "agentId ==")) {
            assertThat(gateway).doesNotContain(leak)
        }
    }

    @Test
    fun `the player streams rather than downloading`() {
        // A fetch-then-play would download a twenty-minute recording before the
        // first second of sound, over a personal data allowance (R14, N43).
        val player = TestPaths.kotlinSources()
            .single { it.name == "Media3AudioPlayback.kt" }.readText()
        assertThat(player).contains("OkHttpDataSource.Factory")
        assertThat(player).contains("Authorization")
    }
}
