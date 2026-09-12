package uz.bonvi.call.domain

/**
 * "Never-false-ready" (UC-03 AC, SPEC §7.8).
 *
 * `capture_state = capturing` requires **every required capability in
 * `granted_working` AND a verified installation**. The home screen and the
 * state sent to the server are computed from THIS function; there is no second
 * code path that could disagree, which is the whole point — a phone that says
 * "Tayyor" and captures nothing is worse than one that says it is not ready,
 * because nobody goes looking.
 */
object CaptureReadiness {

    /**
     * The capabilities without which capture does not work.
     *
     * `CONTACTS` is absent: it is optional and degrades `contact_name` only
     * (SPEC §7.8), and the app never reads the contact book anyway (N28).
     * `OEM_AUTOSTART` and `OEM_RECORDER` are absent because neither can be
     * verified on every handset — an unverifiable capability reported as
     * `unknown` must not be able to block a working phone, and must not be
     * reported as `granted` either (that false green is how R3 stays invisible).
     */
    val REQUIRED: Set<Capability> = setOf(
        Capability.PHONE_STATE,
        Capability.CALL_LOG,
        Capability.MICROPHONE,
        Capability.NOTIFICATIONS,
        Capability.BATTERY_EXEMPTION,
        Capability.FOREGROUND_SERVICE,
        Capability.SUBSCRIPTION_RESOLUTION,
    )

    // `RECOMMENDED` was here and had no reader. What it encoded — that
    // CALL_PHONE and STORAGE_ACCESS must not block E6 — is already true by
    // construction: neither is in [REQUIRED], and [E2_ORDER] asks for them
    // anyway. A second list saying the same thing is a second list that can
    // disagree.

    enum class CaptureState(val wire: String) {
        /** Everything works and the number is proven or attested. */
        CAPTURING("capturing"),

        /** Enrolled and verified, but a required capability is not working. */
        BLOCKED("blocked"),

        /** The number is not verified yet. */
        NOT_VERIFIED("not_verified"),

        /** No installation bound. */
        NOT_ENROLLED("not_enrolled"),
    }

    data class Readiness(
        val state: CaptureState,
        /** The capabilities standing in the way, in the order E2 asks for them,
         *  so the panel and the phone name the same blocker (SPEC §5.2: "the
         *  blocking capability by name"). */
        val blocking: List<Capability>,
    ) {
        val isCapturing: Boolean get() = state == CaptureState.CAPTURING
    }

    /**
     * @param states the latest result for each capability. A capability with no
     *        entry counts as [CapabilityState.UNKNOWN] — absent is not granted.
     */
    fun evaluate(
        states: Map<Capability, CapabilityState>,
        installationActive: Boolean,
        numberVerified: Boolean,
    ): Readiness {
        val blocking = REQUIRED.filter { states[it] != CapabilityState.GRANTED_WORKING }
            .sortedBy { E2_ORDER.indexOf(it) }

        val state = when {
            !installationActive -> CaptureState.NOT_ENROLLED
            !numberVerified -> CaptureState.NOT_VERIFIED
            blocking.isNotEmpty() -> CaptureState.BLOCKED
            else -> CaptureState.CAPTURING
        }
        return Readiness(state, blocking)
    }

    /**
     * E2's order (SPEC §8.2), chosen so the alarming permissions come **after
     * the agent has seen two easy successes**. That ordering is not decoration:
     * N40 gives 15 unaided minutes on somebody's own phone, and the step where
     * people stop is the first one that looks frightening.
     */
    val E2_ORDER: List<Capability> = listOf(
        Capability.PHONE_STATE,
        Capability.CALL_LOG,
        Capability.NOTIFICATIONS,
        Capability.MICROPHONE,
        Capability.CALL_PHONE,
        Capability.CONTACTS,
        Capability.BATTERY_EXEMPTION,
        Capability.STORAGE_ACCESS,
        Capability.OEM_AUTOSTART,
    )

    /** Optional steps an agent may skip without blocking E6. */
    val OPTIONAL: Set<Capability> = setOf(Capability.CONTACTS, Capability.OEM_AUTOSTART)
}
