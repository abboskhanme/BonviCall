package uz.bonvi.call.domain

/**
 * E3's manufacturer-specific steps (SPEC §8.2, R3).
 *
 * Pure Kotlin and in `domain/` because **two callers need the same answer**:
 * the screen renders the steps, and the enrolment flow decides whether the
 * screen is shown at all. When that predicate lived next to the screen the flow
 * could not ask it, and E3 was simply skipped on every handset — including the
 * MIUI phones it exists for, which are most of this fleet.
 *
 * ⚠️ Where the platform exposes no check, the step is **user-attested and
 * recorded as `unknown`, never as `granted`**. A false green here is exactly
 * how R3 stays invisible: the phone claims autostart is on, the OEM kills the
 * service overnight, and the first anyone hears of it is a month of missing
 * calls. `CapabilityChecks` returns `UNKNOWN` for `oem_autostart` for the same
 * reason.
 */
object OemGuidance {

    /** One OEM step: the manufacturer's own path, as a person reads it on the
     *  screen of their own phone. */
    data class Step(val path: String)

    /**
     * The manufacturers SPEC §8.2 names. Anything else gets no E3 at all —
     * showing an irrelevant step costs a minute of a fifteen-minute budget and
     * teaches the agent that the instructions do not match their phone.
     *
     * The paths stay English because they are the OEM's own menu labels, which
     * are not translated on the handset either; the SENTENCE explaining why is
     * Uzbek and lives in `strings.xml` (CONVENTIONS.md §14).
     */
    fun stepsFor(manufacturer: String): List<Step> = when (manufacturer.lowercase()) {
        "xiaomi", "redmi", "poco" -> listOf(
            Step("Settings › Apps › BonviCall › Autostart"),
            Step("Settings › Battery › App battery saver › BonviCall › No restrictions"),
        )
        "huawei", "honor" -> listOf(
            Step("Settings › Battery › App launch › BonviCall › Manage manually"),
        )
        "oppo", "realme", "oneplus" -> listOf(
            Step("Settings › Battery › Background usage › BonviCall › Allow"),
            Step("Settings › Apps › Auto-start › BonviCall"),
        )
        "samsung" -> listOf(
            Step("Settings › Battery › Background usage limits › Never sleeping apps"),
        )
        "vivo" -> listOf(
            Step("Settings › Battery › High background power consumption › BonviCall"),
        )
        else -> emptyList()
    }

    /** Is E3 shown on this handset at all? */
    fun applies(manufacturer: String): Boolean = stepsFor(manufacturer).isNotEmpty()
}
