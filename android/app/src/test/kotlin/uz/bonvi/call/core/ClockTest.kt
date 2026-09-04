package uz.bonvi.call.core

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Time (CONVENTIONS.md §6, N36).
 *
 * The rule this test protects is the one that produces nonsense in the panel
 * when it is broken: a duration is measured with the MONOTONIC clock, so a user
 * changing the phone's clock in the middle of a call cannot produce a negative
 * or wildly long call.
 */
class ClockTest {

    @Test
    fun `a duration is whole seconds and never negative`() {
        assertThat(Clock.durationSeconds(1_000L, 4_500L)).isEqualTo(3)
        assertThat(Clock.durationSeconds(1_000L, 1_000L)).isEqualTo(0)
        // The clock went backwards. Zero is the only honest answer; a negative
        // duration would reach the server and be stored.
        assertThat(Clock.durationSeconds(9_000L, 1_000L)).isEqualTo(0)
    }

    @Test
    fun `a wire timestamp carries an explicit offset`() {
        // 2026-09-04T09:03:11.412Z. Deliberately not epoch 0: Uzbekistan was
        // UTC+6 in 1970 under Soviet time, so a test written against the epoch
        // asserts a historical offset the app will never produce — the first
        // version of this test did exactly that and failed.
        val wire = Clock.toWire(1_772_615_791_412L, Clock.TASHKENT)

        assertThat(wire).startsWith("2026-")
        assertThat(wire).endsWith("+05:00")
        // ISO-8601 with an explicit offset (N36), never a bare local time.
        assertThat(wire).contains("T")
    }

    @Test
    fun `the business zone is named once`() {
        assertThat(Clock.TASHKENT.id).isEqualTo("Asia/Tashkent")
    }
}
