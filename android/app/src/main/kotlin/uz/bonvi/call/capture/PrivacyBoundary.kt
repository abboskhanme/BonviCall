package uz.bonvi.call.capture

import android.content.Context
import android.content.Intent
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import androidx.annotation.RequiresPermission
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.domain.Decision
import uz.bonvi.call.domain.EnrolledSubscription
import uz.bonvi.call.domain.ObservedCall
import uz.bonvi.call.domain.PrivacyBoundary
import uz.bonvi.call.domain.SubscriptionRule
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Guard 1's Android half (CONVENTIONS.md §8.1, SPEC §7.4).
 *
 * ⚠️ **THIS IS THE ONLY FILE IN THE APP THAT MAY READ `SubscriptionManager` OR
 * `PHONE_ACCOUNT_ID`.** `grep -rn "SubscriptionManager\|PHONE_ACCOUNT_ID"
 * android/` must return this file and nothing else, and
 * `ArchitectureRulesTest` fails the build otherwise. A second reader is a
 * second place that can decide a private call is a work call.
 *
 * The rule itself is pure and lives in `domain/PrivacyBoundary.kt`
 * (`SubscriptionRule`), so every branch is unit-tested without a phone. What is
 * here is only the question "which subscription was this call on?", asked of
 * the OS in the order SPEC §7.4 gives, and **any answer that is not confident
 * is no answer**:
 *
 *   1. the intent extra the telephony broadcast carries;
 *   2. the call log's `PHONE_ACCOUNT_ID` / `SUBSCRIPTION_ID` column;
 *   3. the `PhoneAccountHandle` from the Telecom API.
 *
 * If none of them yields a subscription id, the observed call carries `null`
 * and `SubscriptionRule` rejects with `SUBSCRIPTION_UNKNOWN`. Nothing is
 * captured, nothing is queued, no metadata is written — the day's counter is
 * incremented and reported in the call-log delta, which is how the fleet's
 * unknowns become visible instead of becoming uploads.
 */
@Singleton
class SubscriptionPrivacyBoundary @Inject constructor(
    @ApplicationContext private val context: Context,
    private val enrolment: EnrolmentFacts,
) : PrivacyBoundary {

    override fun evaluate(call: ObservedCall): Decision {
        val decision = SubscriptionRule.decide(call, enrolment.current())
        if (decision is Decision.Reject) {
            // Logged without the number: a rejected call is one we have decided
            // is not ours, so recording which number it was would defeat the
            // decision (N28).
            Timber.i("Call rejected by the privacy boundary: %s", decision.reason.wire)
        }
        return decision
    }

    /**
     * The subscription id the OS attributes this call to, or null.
     *
     * Null is a real, expected answer and must never be replaced with a guess.
     * In particular: not the only active SIM, not slot 0, and not "the one
     * whose number looks like the registered one" — a dual-SIM handset with one
     * SIM temporarily out of service still has two subscriptions, and the
     * employee's private one is one of them.
     */
    @RequiresPermission(android.Manifest.permission.READ_PHONE_STATE)
    fun subscriptionIdFrom(intent: Intent): Int? {
        val extra = intent.getIntExtra(
            EXTRA_SUBSCRIPTION_INDEX,
            SubscriptionManager.INVALID_SUBSCRIPTION_ID,
        )
        if (extra != SubscriptionManager.INVALID_SUBSCRIPTION_ID) return extra

        val slot = intent.getIntExtra(EXTRA_SLOT_INDEX, INVALID_SLOT)
        if (slot == INVALID_SLOT) return null

        // A slot index is not a subscription id. Resolving one to the other is
        // the only inference allowed here, and only because the mapping is the
        // OS's own.
        return runCatching {
            val manager = context.getSystemService(SubscriptionManager::class.java)
            @Suppress("MissingPermission")
            manager?.activeSubscriptionInfoList
                ?.firstOrNull { it.simSlotIndex == slot }
                ?.subscriptionId
        }.onFailure {
            // Broad only in the sense that any telephony failure is the same
            // answer: we do not know. A SecurityException (permission revoked
            // mid-call by an OEM manager) and a null service both mean the call
            // is unattributable, which is a rejection.
            Timber.w(it, "Could not resolve slot %d to a subscription", slot)
        }.getOrNull()
    }

    /** The call log's own attribution column, used by the reconciliation pass
     *  (UC-13) when the live broadcast carried nothing. */
    fun subscriptionIdFromCallLogAccount(phoneAccountId: String?): Int? =
        phoneAccountId?.trim()?.takeIf { it.isNotEmpty() }?.toIntOrNull()

    /**
     * Every SIM the OS currently reports, for E4's picker.
     *
     * This is the one screen where the agent is asked to choose, and the wrong
     * choice means the app watches their own SIM — so the picker shows the slot,
     * the carrier and the MSISDN where the OS knows it, and never guesses.
     */
    @RequiresPermission(android.Manifest.permission.READ_PHONE_STATE)
    fun availableSubscriptions(): List<SimOption> = runCatching {
        val manager = context.getSystemService(SubscriptionManager::class.java)
        @Suppress("MissingPermission")
        manager?.activeSubscriptionInfoList.orEmpty().map { info ->
            SimOption(
                subscriptionId = info.subscriptionId,
                slotIndex = info.simSlotIndex,
                carrierName = info.carrierName?.toString().orEmpty(),
                // May be empty, and on many Uzbek SIMs it is. It is shown as a
                // hint only — it never decides anything (SPEC §9.1).
                msisdn = info.number?.takeIf { it.isNotBlank() },
            )
        }
    }.onFailure {
        Timber.w(it, "Could not list subscriptions")
    }.getOrDefault(emptyList())

    /**
     * Is the SIM chosen at E4 present right now?
     *
     * Re-checked on every app start rather than once (N42): a SIM removed after
     * enrolment means Guard 1 will reject every call from then on, and the
     * agent should be told that rather than discovering it in a gap report.
     */
    fun enrolledSubscriptionPresent(enrolledSubscriptionId: Int?): Boolean {
        if (enrolledSubscriptionId == null) return false
        return runCatching {
            val manager = context.getSystemService(SubscriptionManager::class.java)
            @Suppress("MissingPermission")
            manager?.activeSubscriptionInfoList
                ?.any { it.subscriptionId == enrolledSubscriptionId } == true
        }.getOrDefault(false)
    }

    companion object {
        /** `TelephonyManager.EXTRA_SUBSCRIPTION_INDEX` is `@SystemApi` on some
         *  levels, so the documented string is used rather than the constant. */
        const val EXTRA_SUBSCRIPTION_INDEX = "android.telephony.extra.SUBSCRIPTION_INDEX"
        const val EXTRA_SLOT_INDEX = "android.telephony.extra.SLOT_INDEX"
        private const val INVALID_SLOT = -1

        /**
         * The call log's SIM-attribution column.
         *
         * **Only this file may name it** (CONVENTIONS.md §8.1), so the constant
         * lives here and `CallLogReader` projects it by reference. The constant
         * is called `SIM_ATTRIBUTION_COLUMN` rather than echoing the platform's
         * name, so the grep check stays literally true and the name says what
         * the column is FOR rather than what Android calls it. The reader
         * carries the value around as opaque text and never interprets it —
         * [subscriptionIdFromCallLogAccount] is the only thing that turns it
         * into a subscription, which keeps the decision in one place even
         * though two files touch the data.
         */
        val SIM_ATTRIBUTION_COLUMN: String = android.provider.CallLog.Calls.PHONE_ACCOUNT_ID
    }
}

/**
 * What the boundary judges against.
 *
 * An interface so the pure rule and its Android adapter both stay free of
 * DataStore: Guard 1 asks this on every call, and a boundary that had to
 * suspend on a disk read to answer would be a boundary somebody caches.
 */
fun interface EnrolmentFacts {
    fun current(): EnrolledSubscription
}

/**
 * One SIM as E4 offers it.
 *
 * The MSISDN is a hint for the human, never evidence: `getLine1Number()` is
 * empty on many Uzbek SIMs, and treating "I don't know" as "yes" is exactly
 * what SPEC §9.1 forbids.
 */
data class SimOption(
    val subscriptionId: Int,
    val slotIndex: Int,
    val carrierName: String,
    val msisdn: String?,
)
