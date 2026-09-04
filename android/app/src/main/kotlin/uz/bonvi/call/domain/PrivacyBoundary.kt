package uz.bonvi.call.domain

/**
 * THE PRIVACY BOUNDARY — the pure half. Read CONVENTIONS.md §8 and SPEC §7.4
 * before changing anything in this file.
 *
 * The handset belongs to the employee. The OEM recordings folder holds their
 * private calls next to their work calls, and the company has no claim on the
 * first kind. **Capturing a private call by accident is a worse failure than
 * missing a work call**, and this file is where that sentence becomes code.
 *
 * ═══ Where the two halves live ═════════════════════════════════════════════
 * CONVENTIONS.md §8.1 puts `PrivacyBoundary.kt` under `capture/`; SPEC §7.1
 * lists `Decision` and `PrivacyBoundary` among `domain/`'s pure Kotlin types.
 * Both are satisfied and neither is bent:
 *
 *   • `domain/PrivacyBoundary.kt`  (this file) — the TYPES and the RULE. Pure
 *     Kotlin, no Android imports, so every branch is unit-tested without a
 *     phone. `PrivacyBoundaryTest` does exactly that.
 *   • `capture/PrivacyBoundary.kt` — the one Android adapter, and the ONLY file
 *     in the app that touches `SubscriptionManager` or `PHONE_ACCOUNT_ID`.
 *     `grep -rn "SubscriptionManager\|PHONE_ACCOUNT_ID" android/` returns that
 *     one file, which is the check §8.1 asks for.
 *
 * ═══ The boundary is a TYPE, not a policy ══════════════════════════════════
 * [Decision.Capture] is the proof that a call was placed on the registered
 * subscription, and `OemHarvestStrategy` is constructed with one. A caller who
 * has not passed [PrivacyBoundary.evaluate] cannot EXPRESS the call to the
 * locator — that signature is the enforcement, and routing around it means
 * deleting a parameter, which a reviewer sees.
 */
sealed interface Decision {

    /**
     * Proof that this call is on the registered number.
     *
     * The only producer is [PrivacyBoundary.evaluate]. Nothing else may
     * construct one outside a test.
     */
    data class Capture(
        val subscriptionId: Int,
        val registeredNumber: String,
        /** Wall-clock, milliseconds. The harvest window is computed from these. */
        val answeredAtEpochMillis: Long,
        val endedAtEpochMillis: Long,
    ) : Decision

    data class Reject(val reason: RejectReason) : Decision
}

enum class RejectReason(val wire: String) {
    /**
     * The OS would not identify the call's subscription. **Fail closed.** This
     * is the case the whole boundary exists for: on a dual-SIM handset
     * "probably the work SIM" is how a private conversation gets uploaded.
     * Counted in the call-log delta so the gap report shows it (SPEC §4.4).
     */
    SUBSCRIPTION_UNKNOWN("subscription_unknown"),

    /** Identified, and it is the employee's own SIM. Not ours. */
    NOT_REGISTERED_SUBSCRIPTION("not_registered_subscription"),

    /** No installation is bound yet, or it was revoked (UC-08). */
    NOT_ENROLLED("not_enrolled"),

    /** The call never reached a state that could carry audio — no end time.
     *  Rejected rather than guessed: a window with an invented end is a window
     *  that can reach a file it should not. */
    INCOMPLETE_CALL("incomplete_call"),
}

/** What the service saw, before any judgement.
 *
 * Deliberately minimal: everything here is discarded when the decision is
 * [Decision.Reject], so the less it carries the less there is to leak. There is
 * no contact name, no call content and no location in this type, and none may
 * be added. */
data class ObservedCall(
    /** From `EXTRA_SUBSCRIPTION_INDEX`, the call log, or the Telecom API.
     *  Null means the OS would not say — which is a rejection, not a guess. */
    val subscriptionId: Int?,
    val phoneAccountId: String?,
    val direction: CallDirection,
    val startedAtEpochMillis: Long,
    val answeredAtEpochMillis: Long?,
    val endedAtEpochMillis: Long?,
)

/** The enrolment facts the boundary judges against. Null [subscriptionId] means
 *  this installation has not finished binding a SIM. */
data class EnrolledSubscription(
    val subscriptionId: Int?,
    val registeredNumber: String?,
    val isActive: Boolean,
)

/**
 * Guard 1 (SPEC §7.4). The only producer of [Decision.Capture].
 *
 * Split out as a `fun interface` so the Android adapter and the rule are
 * separable: the adapter's job is to answer "which subscription was this call
 * on?" and this rule's job is to decide what that answer means.
 */
fun interface PrivacyBoundary {
    fun evaluate(call: ObservedCall): Decision
}

/**
 * The rule, as a pure function.
 *
 * Order matters and each step fails closed:
 *
 *  1. Not enrolled, or the installation is revoked → nothing is ours.
 *  2. The OS did not identify the subscription → **unknown is not a match.**
 *     This is the branch that gets written the wrong way round when somebody is
 *     in a hurry: "we could not tell, so assume it is the work SIM" uploads the
 *     employee's private calls. Never infer it from the number dialled, from
 *     the SIM slot index, or from there being only one SIM active right now.
 *  3. Identified and not the enrolled subscription → the employee's own SIM.
 *  4. No end time → no window, so no capture. The metadata path may still run;
 *     what is refused here is the audio.
 */
object SubscriptionRule {

    fun decide(call: ObservedCall, enrolment: EnrolledSubscription): Decision {
        val enrolledId = enrolment.subscriptionId
        val registeredNumber = enrolment.registeredNumber
        if (!enrolment.isActive || enrolledId == null || registeredNumber.isNullOrBlank()) {
            return Decision.Reject(RejectReason.NOT_ENROLLED)
        }

        val observedId = call.subscriptionId
            ?: return Decision.Reject(RejectReason.SUBSCRIPTION_UNKNOWN)

        if (observedId != enrolledId) {
            return Decision.Reject(RejectReason.NOT_REGISTERED_SUBSCRIPTION)
        }

        val endedAt = call.endedAtEpochMillis
            ?: return Decision.Reject(RejectReason.INCOMPLETE_CALL)

        // An unanswered call has no answer time. The window then starts at the
        // call's start — it is still a window bounded by this call, and an
        // unanswered call rarely has a recording anyway.
        val answeredAt = call.answeredAtEpochMillis ?: call.startedAtEpochMillis

        return Decision.Capture(
            subscriptionId = enrolledId,
            registeredNumber = registeredNumber,
            answeredAtEpochMillis = answeredAt,
            endedAtEpochMillis = endedAt,
        )
    }
}
