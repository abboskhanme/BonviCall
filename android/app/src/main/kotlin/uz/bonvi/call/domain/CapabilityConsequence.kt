package uz.bonvi.call.domain

/**
 * What it costs to continue without a capability (E2, UC-14).
 *
 * ═══ Why E2 must always be advanceable ═════════════════════════════════════
 * A handset whose microphone the OEM blocks is **a working installation that
 * logs calls without audio**. That is a supported state: `recording_route_
 * unavailable` exists for it, the gap report counts it, the panel renders it,
 * and UC-14 says the call is always logged with a reason from the closed enum
 * even when audio is impossible.
 *
 * Refusing to enrol that phone turns a degraded-but-useful installation into
 * **no installation at all**, which is strictly worse for the same handset —
 * and it strands the agent on a screen whose own text tells them retrying will
 * not help.
 *
 * So every step can be passed. What changes with severity is **what the person
 * is told they are giving up**, because this must be a named consequence and
 * not a hidden escape hatch. The capability state is reported either way, so
 * the panel knows exactly which one is missing on which phone — which is the
 * funnel doing its job, and far more useful than a phone that never appears.
 */
enum class CapabilityConsequence {
    /** Nothing is lost. `contacts` degrades a name to a number; `oem_autostart`
     *  cannot be verified on most handsets anyway. */
    NONE,

    /**
     * Calls are still **qayd etiladi** — logged, with direction, numbers,
     * timestamps and duration — but not **yozib olinadi**. The distinction the
     * whole product rests on, and the one place a person meets it.
     */
    AUDIO_ONLY,

    /**
     * Nothing is captured until this is fixed. Still advanceable: an enrolled
     * phone that reports `BLOCKED` and names its blocker is visible to an
     * admin, and an unenrolled one is not.
     */
    CAPTURE_BLOCKED,
    ;

    companion object {
        fun of(capability: Capability): CapabilityConsequence = when (capability) {
            // Optional by SPEC §8.2 — `contacts` is marked *ixtiyoriy*, and
            // `oem_autostart` reports `unknown` on most manufacturers because
            // the platform exposes no check.
            Capability.CONTACTS, Capability.OEM_AUTOSTART -> NONE

            // Audio only. The call still reaches the panel with a reason.
            Capability.MICROPHONE, Capability.STORAGE_ACCESS, Capability.OEM_RECORDER ->
                AUDIO_ONLY

            // Without these the service cannot see a call at all, or the OS
            // stops it before one arrives.
            Capability.PHONE_STATE, Capability.CALL_LOG, Capability.NOTIFICATIONS,
            Capability.BATTERY_EXEMPTION, Capability.FOREGROUND_SERVICE,
            Capability.SUBSCRIPTION_RESOLUTION,
            -> CAPTURE_BLOCKED

            // UC-16 only: click-to-call stops working, capture does not.
            Capability.CALL_PHONE -> NONE
        }
    }
}
