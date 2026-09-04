package uz.bonvi.call.domain

/**
 * One capability's verified result.
 *
 * The rule the whole enrolment rests on (SPEC §7.8): **every check exercises
 * the capability, never reads the permission flag.** "Did you enable it?" with
 * a checkbox is how a rollout looks fine and captures nothing, and UC-03 names
 * the specific trap — an OEM permission manager reporting `granted` while
 * blocking the call, which produces [CapabilityState.GRANTED_NOT_WORKING].
 * Retrying the system dialog will never fix that state, so the UI must not
 * offer it as the next action.
 */
data class CapabilityResult(
    val capability: Capability,
    val state: CapabilityState,
    /** What the check actually found, e.g. "1s test capture 32 kB". Shown to
     *  the agent and sent to the panel, because "it did not work" without
     *  evidence is an unactionable support call. */
    val detail: String? = null,
) {
    val isWorking: Boolean get() = state == CapabilityState.GRANTED_WORKING

    /** Asking again will not help: the system dialog is not what is refusing. */
    val needsSettingsScreen: Boolean
        get() = state == CapabilityState.DENIED_PERMANENTLY ||
            state == CapabilityState.GRANTED_NOT_WORKING
}

/**
 * Checks one capability by using it.
 *
 * Implementations live in `enrolment/`, except the microphone probe, which is a
 * one-second `AudioRecord` capture and therefore belongs under `capture/` —
 * media APIs appear in exactly one package (SPEC §7.1), and that rule is
 * enforced by `ArchitectureRulesTest`.
 */
fun interface CapabilityCheck {
    suspend fun check(): CapabilityResult
}
