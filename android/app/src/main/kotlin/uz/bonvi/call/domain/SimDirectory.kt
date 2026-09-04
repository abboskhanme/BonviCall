package uz.bonvi.call.domain

/**
 * The SIMs E4 offers, as `ui/` is allowed to see them.
 *
 * ═══ Why this interface exists ═════════════════════════════════════════════
 * `ui/` may not reach into `capture/` or `data/remote` directly (SPEC §7.1) —
 * "the one layering rule worth enforcing without a module system, because it is
 * the one that decides whether the enrolment screens can be tested without a
 * phone". `ArchitectureRulesTest` caught `MainActivity` importing
 * `SubscriptionPrivacyBoundary` and failed the build, which is the rule working.
 *
 * The fix is not a wider rule, it is this seam: `capture/` keeps the ONLY
 * reader of `SubscriptionManager` (CONVENTIONS.md §8.1) and exposes the answer
 * as pure data. E4 gets a list it can render and a test can fake.
 */
data class SimOptionInfo(
    val subscriptionId: Int,
    val slotIndex: Int,
    val carrierName: String,
    /**
     * The SIM's own MSISDN where the OS knows it — a HINT for the human and
     * never evidence. It is empty on many Uzbek SIMs, and treating "I don't
     * know" as "yes" is exactly what SPEC §9.1 forbids.
     */
    val msisdn: String?,
)

fun interface SimDirectory {
    /** Empty when the OS will not say — which is a correct answer, not an
     *  error, and nothing downstream may read it as a match. */
    fun available(): List<SimOptionInfo>
}
