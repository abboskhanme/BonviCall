package uz.bonvi.call.core

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * N26: a token, a password, an enrolment code or a verification code never
 * appears in a log line.
 *
 * These are the employees' own phones and log buffers end up in support chats.
 * An enrolment code is a credential that binds a handset to a company number,
 * so it is redacted with the same rule as a password.
 */
class RedactingTreeTest {

    @Test
    fun `an access token is reduced to its last four characters`() {
        val redacted = RedactingTree.redact("""{"access_token":"eyJhbGciOiJIUzI1NiJ9.abcdWXYZ"}""")

        assertThat(redacted).doesNotContain("eyJhbGciOiJIUzI1NiJ9")
        assertThat(redacted).contains("WXYZ")
    }

    @Test
    fun `a bearer header is redacted even without a key name`() {
        val redacted = RedactingTree.redact("Authorization: Bearer abcdefghijkl1234")

        assertThat(redacted).doesNotContain("abcdefghijkl")
        assertThat(redacted).contains("1234")
    }

    @Test
    fun `an enrolment code is a credential and is redacted`() {
        val redacted = RedactingTree.redact("redeem code=ABCD-EFGH-9876 ok")

        assertThat(redacted).doesNotContain("ABCD-EFGH")
        assertThat(redacted).contains("9876")
    }

    @Test
    fun `a short secret is not partially revealed`() {
        // Four characters or fewer: showing "the last four" would show all of
        // it, so nothing is shown.
        assertThat(RedactingTree.redact("password=1234")).doesNotContain("1234")
    }

    @Test
    fun `ordinary log lines are left alone`() {
        val message = "Uploaded 12 calls in 3400 ms, queue depth 5"
        assertThat(RedactingTree.redact(message)).isEqualTo(message)
    }
}
