package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Number verification (UC-04, SPEC §9.1, R19).
 *
 * **The load-bearing assertion is that `getLine1Number()` returning nothing is
 * NEVER a match.** On many Uzbek SIMs it is simply empty, which is why route 2
 * carries the weight; and the failure treating it as a match would cause —
 * attributing a handset to a number it does not hold — puts every call that
 * phone ever makes against the wrong salesperson, silently, forever.
 *
 * UC-04 names this as an explicit requirement. This test may not be deleted,
 * skipped or weakened.
 */
class NumberVerificationTest {

    private val registered = "+998901112233"

    @Test
    fun `null is never a match`() {
        assertThat(NumberVerification.checkMsisdn(null, registered))
            .isEqualTo(NumberVerification.MsisdnOutcome.EMPTY)
    }

    @Test
    fun `empty and whitespace are never a match`() {
        for (raw in listOf("", "   ", "\t", "\n")) {
            assertThat(NumberVerification.checkMsisdn(raw, registered))
                .isEqualTo(NumberVerification.MsisdnOutcome.EMPTY)
        }
    }

    @Test
    fun `fewer than nine digits is never a match`() {
        // Not even when those digits are a suffix of the registered number.
        for (raw in listOf("1112233", "2233", "+998", "0")) {
            assertThat(NumberVerification.checkMsisdn(raw, registered))
                .isEqualTo(NumberVerification.MsisdnOutcome.EMPTY)
        }
    }

    @Test
    fun `the same number in any format is a match`() {
        // Same rule and same vectors as the server: Phone.phoneKey, last 9
        // digits (N37). Not a second normalisation — two implementations of
        // "the same number" is how a match becomes a coin toss.
        for (raw in listOf(
            "+998901112233",
            "998901112233",
            "901112233",
            "+998 90 111-22-33",
            "(90) 111 22 33",
            "8 90 111 22 33",
        )) {
            assertThat(NumberVerification.checkMsisdn(raw, registered))
                .isEqualTo(NumberVerification.MsisdnOutcome.MATCHED)
        }
    }

    @Test
    fun `a different number is a mismatch, not an empty`() {
        // Usually the wrong SIM was chosen at E4, and the two need different
        // sentences: "choose the other SIM" versus "call this number".
        assertThat(NumberVerification.checkMsisdn("+998907776655", registered))
            .isEqualTo(NumberVerification.MsisdnOutcome.MISMATCH)
    }

    @Test
    fun `an unparseable registered number cannot silently match anything`() {
        assertThat(NumberVerification.checkMsisdn("901112233", "not-a-number"))
            .isEqualTo(NumberVerification.MsisdnOutcome.EMPTY)
    }

    @Test
    fun `attested is not proven, and says so`() {
        // SPEC §9.3: attested is weaker evidence and is rendered differently
        // everywhere it appears, so the identity anchor never silently
        // degrades.
        assertThat(NumberVerification.Method.ADMIN_ATTESTED.isProven).isFalse()
        assertThat(NumberVerification.Method.SIM_MSISDN.isProven).isTrue()
        assertThat(NumberVerification.Method.CALLBACK.isProven).isTrue()
    }

    @Test
    fun `no_caller_id sends the agent to a person, not round the loop again`() {
        // R19 happening. Retrying will never work on that operator.
        val outcome = NumberVerification.CallbackOutcome.NO_CALLER_ID
        assertThat(outcome.needsAssistedInstall).isTrue()
        assertThat(outcome.isRetryable).isFalse()

        assertThat(NumberVerification.CallbackOutcome.TIMEOUT.isRetryable).isTrue()
        assertThat(NumberVerification.CallbackOutcome.MISMATCH.isRetryable).isTrue()
        assertThat(NumberVerification.CallbackOutcome.RECEIVER_DOWN.isRetryable).isFalse()
    }

    @Test
    fun `there are exactly two device-side routes`() {
        // SMS is out of scope, and route 3 is an ADMIN action rather than
        // something the handset can do. If a third device route ever appears
        // here, it needs a change request first (SPEC §9.3).
        val deviceRoutes = NumberVerification.Method.entries.filter { it.isProven }
        assertThat(deviceRoutes).containsExactly(
            NumberVerification.Method.SIM_MSISDN,
            NumberVerification.Method.CALLBACK,
        )
    }
}
