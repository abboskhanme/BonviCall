package uz.bonvi.call.service

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.service.work.CommandFreshness

/**
 * Click-to-call staleness (T80, UC-16).
 *
 * The transport is not the risk — the WebSocket hub measures 13 ms against
 * UC-16's 5 000 ms bar. **Doze on MIUI and EMUI is.** A phone that was asleep
 * can receive a ten-minute-old dial command the moment it wakes, and dialling
 * it then is worse than not dialling it at all: somebody answers a call the
 * salesperson has forgotten making, about a conversation that already happened.
 */
class CommandFreshnessTest {

    private val freshness = CommandFreshness()
    private val now = 1_772_615_791_000L

    @Test
    fun `a command issued moments ago is dialled`() {
        assertThat(freshness.isFresh(now - 13, now)).isTrue()
        assertThat(freshness.isFresh(now - 5_000, now)).isTrue()
    }

    @Test
    fun `a command that survived a doze window is still dialled`() {
        // Long enough to survive a normal doze window and a slow reconnect.
        assertThat(freshness.isFresh(now - 90_000, now)).isTrue()
    }

    @Test
    fun `a command older than two minutes is discarded`() {
        assertThat(freshness.isFresh(now - CommandFreshness.MAX_AGE_MS - 1, now)).isFalse()
        assertThat(freshness.isFresh(now - 10 * 60_000, now)).isFalse()
    }

    @Test
    fun `the boundary is inclusive, so exactly two minutes still dials`() {
        assertThat(freshness.isFresh(now - CommandFreshness.MAX_AGE_MS, now)).isTrue()
    }

    @Test
    fun `a discarded command reports HOW late it was`() {
        // The panel has to tell "arrived late" from "never arrived": those are
        // different faults with different fixes, and a silent drop looks like
        // the second one.
        assertThat(freshness.stalenessReason(now - 600_000, now))
            .isEqualTo("discarded_stale_600s")
    }

    @Test
    fun `the limit is two minutes, not UC-16's five-second target`() {
        // 5 s is the bar for a phone that is awake. This is the outer limit of
        // "late but still useful".
        assertThat(CommandFreshness.MAX_AGE_MS).isEqualTo(120_000L)
    }
}
