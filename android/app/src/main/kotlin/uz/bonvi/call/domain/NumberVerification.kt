package uz.bonvi.call.domain

import uz.bonvi.call.core.Phone

/**
 * Number verification (UC-04, SPEC §9, R19).
 *
 * **Two routes, in order, and since SMS left scope the second one carries the
 * weight.** A third — admin attestation — exists behind them and is
 * deliberately weaker and deliberately visible.
 *
 * The rule below is pure so the one branch that matters can be asserted rather
 * than reviewed.
 */
object NumberVerification {

    /**
     * Does this verification state mean the server will now accept the
     * handset's calls?
     *
     * Three states do, at three different strengths, and the list lives HERE
     * because two callers need the same answer: the repository, deciding
     * whether a response carried a real token pair, and the ViewModel,
     * deciding whether E6 may be reached. It was written out twice and the two
     * copies had already drifted — the repository knew about a third state the
     * readiness check did not, so a self-declared handset held real tokens and
     * still rendered as unenrolled.
     */
    fun isBound(state: String?): Boolean = state in BOUND_STATES

    private val BOUND_STATES = setOf("matched", "attested", "self_declared")

    /** Why route 1 could not prove the match. Wire names from `EnrolmentOutcome`. */
    enum class MsisdnOutcome(val wire: String) {
        MATCHED("ok"),

        /** The SIM did not report a number, or reported something too short to
         *  be one. **On many Uzbek SIMs this is simply the normal answer**,
         *  which is exactly why route 2 exists and carries the weight. */
        EMPTY("msisdn_empty"),

        /** The SIM reported a number and it is not the registered one — usually
         *  the wrong SIM was chosen at E4. */
        MISMATCH("number_mismatch"),
    }

    /**
     * Route 1 (SPEC §9.1): compare the SIM's own MSISDN with the registered
     * number, on the last 9 digits (N37).
     *
     * ⚠️ **`null`, empty, whitespace, or fewer than 9 digits is NEVER a match.**
     * It is [MsisdnOutcome.EMPTY] and the flow moves to route 2. UC-04 states
     * this as an explicit requirement and asserts it with a test, because the
     * failure it prevents — treating "I don't know" as "yes" — would attribute
     * a phone to a number it does not hold, and every call that phone ever
     * makes would be filed against the wrong salesperson.
     *
     * The comparison is [Phone.phoneKey], the same function and the same
     * `contract/phone-vectors.json` the server uses. Not a second
     * normalisation: two implementations of "the same number" is how a match
     * becomes a coin toss.
     */
    fun checkMsisdn(line1Number: String?, registeredNumber: String): MsisdnOutcome {
        val simKey = Phone.phoneKey(line1Number) ?: return MsisdnOutcome.EMPTY
        val registeredKey = Phone.phoneKey(registeredNumber) ?: return MsisdnOutcome.EMPTY
        return if (simKey == registeredKey) MsisdnOutcome.MATCHED else MsisdnOutcome.MISMATCH
    }

    /**
     * How the number was proven, once it has been.
     *
     * `ADMIN_ATTESTED` is weaker evidence than the other two and is rendered
     * differently everywhere it appears (SPEC §9.3), **so the identity anchor
     * never silently degrades**. It exists for R19: an agent whose operator
     * suppresses caller ID cannot pass route 2 on that operator, and the
     * alternative to attestation is that person never being enrolled.
     */
    enum class Method(val wire: String, val isProven: Boolean) {
        SIM_MSISDN("sim_msisdn", isProven = true),
        CALLBACK("callback", isProven = true),

        /** An admin vouched for it, with a mandatory reason and an audit row.
         *  Not proven — vouched for. */
        ADMIN_ATTESTED("admin_attested", isProven = false),

        /**
         * The weakest binding of the four, and the ordinary one on this fleet.
         *
         * It says that whoever held the single-use code an admin issued **for
         * this one number** typed it into this handset. No line was proven.
         *
         * It exists because the two proving routes are frequently both
         * unavailable at once here — Uzbek SIMs leave `getLine1Number()` empty
         * and the callback needs a receiver line — and a handset with no route
         * to `active` captures nothing and reports nothing, so nobody can even
         * see that it is stuck. An enrolled phone with a visibly unproven
         * binding is strictly better than that, and an admin can still attest
         * it afterwards.
         */
        SELF_DECLARED("self_declared", isProven = false),
        ;

        companion object {
            fun fromWire(wire: String?): Method? = entries.firstOrNull { it.wire == wire }
        }
    }

    /** Route 2's outcomes (SPEC §9.2 step 5), each distinct and each recorded. */
    enum class CallbackOutcome(val wire: String) {
        MATCHED("ok"),

        /**
         * The operator withheld caller ID. **This is R19 happening.** The agent
         * cannot pass this route on this operator, so the app shows the
         * assisted path and the panel marks `needs_assisted_install` — it does
         * not ask them to try again, which would never work.
         */
        NO_CALLER_ID("no_caller_id"),

        /** The call came from a different number, usually the wrong SIM. The
         *  installation stays `pending`: a callback from a different number
         *  must leave the device UNENROLLED (UC-04 AC). */
        MISMATCH("number_mismatch"),

        /** The 5-minute window expired. Retrying is fine and each retry is a new
         *  row, so the funnel shows how many attempts a person needed. */
        TIMEOUT("timeout"),

        /** Every receiver is down. The agent is told to contact the admin
         *  rather than dialling into nothing. */
        RECEIVER_DOWN("receiver_down"),
        ;

        /** True when trying again on this handset could plausibly work. */
        val isRetryable: Boolean
            get() = this == TIMEOUT || this == MISMATCH

        /** True when the only way forward is a person: R19's assisted path. */
        val needsAssistedInstall: Boolean
            get() = this == NO_CALLER_ID

        companion object {
            fun fromWire(wire: String?): CallbackOutcome? = entries.firstOrNull { it.wire == wire }
        }
    }
}
