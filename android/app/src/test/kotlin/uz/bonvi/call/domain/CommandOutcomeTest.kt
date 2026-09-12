package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * A refused dial says WHY, in the server's vocabulary (UC-16).
 *
 * The panel groups commands by failure reason, so the difference between
 * `no_permission` and `os_refused` is the difference between "CALL_PHONE was
 * switched off on eleven handsets" — one message to the fleet — and "something
 * went wrong", which is eleven separate support calls.
 */
class CommandOutcomeTest {

    @Test
    fun `a stale command is reported as stale, whatever its age`() {
        // DialCommand encodes the age in the string; the bucket is the same.
        assertThat(CommandOutcome.forDialDiscard("discarded_stale_130s"))
            .isEqualTo(CommandFailure.DISCARDED_STALE)
        assertThat(CommandOutcome.forDialDiscard("discarded_stale_98000s"))
            .isEqualTo(CommandFailure.DISCARDED_STALE)
    }

    @Test
    fun `a revoked call permission is not filed as an OS refusal`() {
        // The one that matters in the field: CALL_PHONE granted at enrolment
        // and taken away later makes every dial fail SILENTLY on the handset.
        assertThat(CommandOutcome.forDialDiscard("SecurityException"))
            .isEqualTo(CommandFailure.NO_PERMISSION)
    }

    @Test
    fun `a number that is not a number is the panel's problem, not the phone's`() {
        assertThat(CommandOutcome.forDialDiscard("unparseable_number"))
            .isEqualTo(CommandFailure.UNSUPPORTED)
    }

    @Test
    fun `anything the handset itself refused falls to os_refused`() {
        assertThat(CommandOutcome.forDialDiscard("ActivityNotFoundException"))
            .isEqualTo(CommandFailure.OS_REFUSED)
    }
}
