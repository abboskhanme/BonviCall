package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Which verification states mean the server will accept this phone's calls.
 *
 * The rule lived in two places and the copies had drifted: the repository knew
 * about `self_declared` and the readiness check did not, so a handset holding a
 * real token pair still rendered as unenrolled and refused to start capturing.
 * One function now, and these are its cases.
 */
class NumberVerificationBindingTest {

    @Test
    fun `every state that issues a token pair counts as bound`() {
        assertThat(NumberVerification.isBound("matched")).isTrue()
        assertThat(NumberVerification.isBound("attested")).isTrue()
        assertThat(NumberVerification.isBound("self_declared")).isTrue()
    }

    @Test
    fun `a pending or failed verification is not bound`() {
        assertThat(NumberVerification.isBound("pending")).isFalse()
        assertThat(NumberVerification.isBound("failed")).isFalse()
        assertThat(NumberVerification.isBound("expired")).isFalse()
        // The state before the first response, and the one that matters most:
        // absent must never read as bound.
        assertThat(NumberVerification.isBound(null)).isFalse()
    }

    @Test
    fun `a state from a newer server is not bound`() {
        // The fleet cannot be force-updated, so an APK will meet a server that
        // knows states it does not. Unknown must fail closed.
        assertThat(NumberVerification.isBound("some_future_route")).isFalse()
    }

    /**
     * SPEC §9.3: the identity anchor degrades visibly or not at all. Two of the
     * four routes prove a line and two vouch for one, and every screen that
     * renders a binding branches on exactly this.
     */
    @Test
    fun `only the two proving routes are marked proven`() {
        assertThat(NumberVerification.Method.SIM_MSISDN.isProven).isTrue()
        assertThat(NumberVerification.Method.CALLBACK.isProven).isTrue()
        assertThat(NumberVerification.Method.ADMIN_ATTESTED.isProven).isFalse()
        assertThat(NumberVerification.Method.SELF_DECLARED.isProven).isFalse()
    }

    @Test
    fun `every method round-trips through its wire name`() {
        for (method in NumberVerification.Method.entries) {
            assertThat(NumberVerification.Method.fromWire(method.wire)).isEqualTo(method)
        }
    }
}
