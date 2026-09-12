package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test
import uz.bonvi.call.data.local.QueuedCallEntity

/**
 * The upload queue's rules (N8).
 *
 * "Oldest first, parked after five attempts and reported, never deleted" is a
 * sentence in `CONVENTIONS-CLIENT.md` §9. This is that sentence as assertions,
 * because the failure it prevents — a call quietly disappearing from a phone
 * that could not reach the server — is invisible by construction.
 */
class UploadPolicyTest {

    @Test
    fun `a transient failure is retried with growing backoff`() {
        val first = UploadPolicy.onFailure(attemptsSoFar = 0, status = 503, code = "internal_error")
        val second = UploadPolicy.onFailure(attemptsSoFar = 1, status = 503, code = "internal_error")

        assertThat(first).isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
        assertThat(second).isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
        assertThat((second as UploadPolicy.Outcome.Retry).afterSeconds)
            .isGreaterThan((first as UploadPolicy.Outcome.Retry).afterSeconds)
    }

    @Test
    fun `offline is retried - no server means no judgement`() {
        // status 0: the request never reached anything. A phone in a lift is
        // the normal case this whole queue exists for.
        assertThat(UploadPolicy.onFailure(attemptsSoFar = 0, status = 0, code = null))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
    }

    @Test
    fun `the fifth attempt parks the row`() {
        val outcome = UploadPolicy.onFailure(
            attemptsSoFar = UploadPolicy.MAX_ATTEMPTS - 1,
            status = 503,
            code = "internal_error",
        )

        assertThat(outcome).isInstanceOf(UploadPolicy.Outcome.Park::class.java)
    }

    @Test
    fun `a 4xx the server already judged is not retried`() {
        // Replaying a request the server has rejected changes nothing and burns
        // the employee's data against N15's cap.
        assertThat(UploadPolicy.onFailure(0, 409, "audio_not_attributable"))
            .isInstanceOf(UploadPolicy.Outcome.Park::class.java)
        assertThat(UploadPolicy.onFailure(0, 422, "validation_error"))
            .isInstanceOf(UploadPolicy.Outcome.Park::class.java)
    }

    @Test
    fun `429 and 408 are retried because the server asked us to come back`() {
        assertThat(UploadPolicy.onFailure(0, 429, "rate_limited"))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
        assertThat(UploadPolicy.onFailure(0, 408, null))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
    }

    @Test
    fun `an unsupported app version parks and never drops`() {
        // CONVENTIONS.md §4.4: the order is the rule. An old client drains its
        // backlog first and is refused afterwards; refusing an old version must
        // never destroy data. Parking keeps every row for the update.
        val outcome = UploadPolicy.onFailure(0, 426, "app_version_unsupported")

        assertThat(outcome).isInstanceOf(UploadPolicy.Outcome.Park::class.java)
        assertThat((outcome as UploadPolicy.Outcome.Park).reason)
            .isEqualTo("app_version_unsupported")
    }

    @Test
    fun `a parked row is never sendable and never deleted by the policy`() {
        // Asserted through the rule that creates the state rather than through
        // a second predicate describing it: reaching MAX_ATTEMPTS is what
        // parks a row, and being parked is what takes it out of the DAO's
        // `WHERE parkedAtEpochMillis IS NULL`. `isSendable` said the same
        // thing a second time and was deleted for it.
        assertThat(UploadPolicy.onFailure(UploadPolicy.MAX_ATTEMPTS, 503, null))
            .isInstanceOf(UploadPolicy.Outcome.Park::class.java)
        assertThat(UploadPolicy.onFailure(1, 503, null))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)

        // There is no outcome that means "delete". The only delete in the whole
        // queue is confirm(), which runs after the server acknowledges (N11).
        val outcomes = listOf(
            UploadPolicy.onFailure(0, 503, null),
            UploadPolicy.onFailure(9, 503, null),
            UploadPolicy.onFailure(0, 409, null),
        )
        assertThat(outcomes.none { it is UploadPolicy.Outcome.Confirmed }).isTrue()
    }

    @Test
    fun `the attempt limit is decided in one place`() {
        // The schema and the policy must agree, or the queue drains a different
        // number of times than the rule says.
        assertThat(QueuedCallEntity.MAX_ATTEMPTS).isEqualTo(UploadPolicy.MAX_ATTEMPTS)
        assertThat(UploadPolicy.MAX_ATTEMPTS).isEqualTo(5)
    }

    @Test
    fun `a queued row is not parked until something parks it`() {
        val row = QueuedCallEntity(
            clientCallId = "9f1d0a2e-0000-4000-8000-000000000001",
            payloadJson = "{}",
            queuedAtEpochMillis = 1L,
        )

        assertThat(row.isParked).isFalse()
        assertThat(row.copy(parkedAtEpochMillis = 2L).isParked).isTrue()
    }

    // --- An unreachable server (found on the first real handset) -------------
    //
    // A live Redmi Note 14 captured 39 calls over two days and delivered none
    // of them: every row sat parked with `max_attempts`, because the laptop
    // running the server was off overnight and each failed attempt counted.
    // The backoff reaches attempt five after about 1 h 45 m, so any outage
    // longer than an afternoon killed the whole queue permanently — and
    // nothing ever retried a parked row. Each test below fails against the
    // policy as it stood.

    @Test
    fun `an unreachable server never parks a row, however many times it is tried`() {
        for (attempts in 0..50) {
            val outcome = UploadPolicy.onFailure(attempts, 0, UploadPolicy.UNREACHABLE)
            assertThat(outcome).isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
        }
    }

    @Test
    fun `an unreachable server still backs off, and the backoff is capped`() {
        // Counted, so the wait widens and the panel can see how long a handset
        // has been shouting into nothing — just never made permanent.
        val first = UploadPolicy.onFailure(0, 0, UploadPolicy.UNREACHABLE)
        val late = UploadPolicy.onFailure(40, 0, UploadPolicy.UNREACHABLE)
        assertThat((first as UploadPolicy.Outcome.Retry).afterSeconds).isEqualTo(30)
        // Capped rather than unbounded: a phone back after a week must drain
        // that week promptly, not wait longer and longer.
        assertThat((late as UploadPolicy.Outcome.Retry).afterSeconds).isEqualTo(3_600)
    }

    @Test
    fun `an unreadable payload still parks, even though it is also status zero`() {
        // The distinction the fix turns on. Both cases reach the policy with
        // status 0, and only one of them is exempt from the attempt limit: a
        // row that cannot be parsed can never succeed, so it must still come
        // to rest rather than block the queue behind it for ever.
        assertThat(UploadPolicy.onFailure(0, 0, "payload_unreadable"))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
        assertThat(UploadPolicy.onFailure(UploadPolicy.MAX_ATTEMPTS, 0, "payload_unreadable"))
            .isInstanceOf(UploadPolicy.Outcome.Park::class.java)
        // Whereas an unreachable server never does, at any count.
        assertThat(UploadPolicy.onFailure(UploadPolicy.MAX_ATTEMPTS, 0, UploadPolicy.UNREACHABLE))
            .isInstanceOf(UploadPolicy.Outcome.Retry::class.java)
    }

    @Test
    fun `a judged rejection still parks while the server is reachable`() {
        // The fix must not turn the queue into an infinite retry loop against
        // a server that has already said no.
        assertThat(UploadPolicy.onFailure(0, 409, "call_identity_conflict"))
            .isInstanceOf(UploadPolicy.Outcome.Park::class.java)
        assertThat(UploadPolicy.onFailure(UploadPolicy.MAX_ATTEMPTS, 503, null))
            .isInstanceOf(UploadPolicy.Outcome.Park::class.java)
    }
}
