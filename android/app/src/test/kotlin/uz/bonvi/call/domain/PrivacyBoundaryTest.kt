package uz.bonvi.call.domain

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Guard 1 — the dual-SIM decision (CONVENTIONS.md §8, SPEC §7.4).
 *
 * **Fail closed.** Where the OS cannot identify the subscription, the call is
 * unregistered: nothing captured, nothing queued, no metadata written. Missing
 * a work call is a recoverable error; capturing a private one is not.
 *
 * These tests are load-bearing. A PR that changes them has to say why in the
 * commit message (CONVENTIONS.md §8).
 */
class PrivacyBoundaryTest {

    private val enrolled = EnrolledSubscription(
        subscriptionId = 2,
        registeredNumber = "+998901112233",
        isActive = true,
    )

    private fun call(
        subscriptionId: Int?,
        answeredAt: Long? = 1_000L,
        endedAt: Long? = 61_000L,
        direction: CallDirection = CallDirection.OUTGOING,
    ) = ObservedCall(
        subscriptionId = subscriptionId,
        phoneAccountId = null,
        direction = direction,
        startedAtEpochMillis = 500L,
        answeredAtEpochMillis = answeredAt,
        endedAtEpochMillis = endedAt,
    )

    @Test
    fun `a call on the enrolled subscription produces the capture proof`() {
        val decision = SubscriptionRule.decide(call(subscriptionId = 2), enrolled)

        assertThat(decision).isInstanceOf(Decision.Capture::class.java)
        val capture = decision as Decision.Capture
        assertThat(capture.subscriptionId).isEqualTo(2)
        assertThat(capture.registeredNumber).isEqualTo("+998901112233")
        assertThat(capture.answeredAtEpochMillis).isEqualTo(1_000L)
        assertThat(capture.endedAtEpochMillis).isEqualTo(61_000L)
    }

    @Test
    fun `an UNKNOWN subscription is rejected, never assumed to be ours`() {
        // THE test. "We could not tell, so assume it is the work SIM" is how an
        // employee's private conversation gets uploaded, and it is the branch
        // somebody writes the wrong way round in a hurry.
        val decision = SubscriptionRule.decide(call(subscriptionId = null), enrolled)

        assertThat(decision).isEqualTo(Decision.Reject(RejectReason.SUBSCRIPTION_UNKNOWN))
    }

    @Test
    fun `an unknown subscription is rejected even when only one SIM is enrolled`() {
        // A dual-SIM handset with one SIM temporarily out of service still has
        // two subscriptions. "There is only one enrolled, so it must be that
        // one" is the same wrong inference wearing a different hat.
        val decision = SubscriptionRule.decide(call(subscriptionId = null), enrolled)

        assertThat(decision).isNotInstanceOf(Decision.Capture::class.java)
    }

    @Test
    fun `the employee's own SIM is rejected`() {
        val decision = SubscriptionRule.decide(call(subscriptionId = 1), enrolled)

        assertThat(decision).isEqualTo(Decision.Reject(RejectReason.NOT_REGISTERED_SUBSCRIPTION))
    }

    @Test
    fun `nothing is captured before enrolment finishes`() {
        val pending = enrolled.copy(subscriptionId = null)

        assertThat(SubscriptionRule.decide(call(subscriptionId = 2), pending))
            .isEqualTo(Decision.Reject(RejectReason.NOT_ENROLLED))
    }

    @Test
    fun `a revoked installation captures nothing`() {
        // UC-08. Revocation must take effect on the handset, not only in the
        // panel: the phone stops capturing even before it next reaches the
        // server.
        val revoked = enrolled.copy(isActive = false)

        assertThat(SubscriptionRule.decide(call(subscriptionId = 2), revoked))
            .isEqualTo(Decision.Reject(RejectReason.NOT_ENROLLED))
    }

    @Test
    fun `an enrolment with no registered number captures nothing`() {
        val halfBound = enrolled.copy(registeredNumber = "")

        assertThat(SubscriptionRule.decide(call(subscriptionId = 2), halfBound))
            .isEqualTo(Decision.Reject(RejectReason.NOT_ENROLLED))
    }

    @Test
    fun `a call with no end time yields no window`() {
        // No end time means no window, and a window with an invented end is a
        // window that can reach a file it should not.
        val decision = SubscriptionRule.decide(call(subscriptionId = 2, endedAt = null), enrolled)

        assertThat(decision).isEqualTo(Decision.Reject(RejectReason.INCOMPLETE_CALL))
    }

    @Test
    fun `an unanswered call windows from its start rather than being refused`() {
        // UC-09: an unanswered outgoing call is still a call. It rarely has a
        // recording, but the window must be well-formed rather than absent.
        val decision = SubscriptionRule.decide(
            call(subscriptionId = 2, answeredAt = null),
            enrolled,
        )

        assertThat(decision).isInstanceOf(Decision.Capture::class.java)
        assertThat((decision as Decision.Capture).answeredAtEpochMillis).isEqualTo(500L)
    }

    @Test
    fun `every rejection carries a reason the gap report can group by`() {
        // The counter behind SPEC §4.4's call-log delta. A rejection with no
        // name is a fleet-wide silence nobody can explain.
        assertThat(RejectReason.entries.map { it.wire }).containsExactly(
            "subscription_unknown",
            "not_registered_subscription",
            "not_enrolled",
            "incomplete_call",
        )
    }
}
