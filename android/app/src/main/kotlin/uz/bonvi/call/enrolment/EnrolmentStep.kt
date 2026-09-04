package uz.bonvi.call.enrolment

import uz.bonvi.call.core.Clock
import uz.bonvi.call.domain.Capability

/**
 * The six steps, and the stopwatch N40 is measured with (SPEC §8).
 *
 * **N40 is a measurement, not a review: 3 of 3 unaided salespeople reach
 * `capturing` in under 15 minutes each.** The time budget SPEC §8 sets is
 * landing + download 3 min · install past the warnings 3 min · code 1 min ·
 * permissions 3 min · verification 1 min — 11 minutes, with 4 of slack.
 *
 * The app timestamps every step and posts `step_timing`, so the bar keeps being
 * measured on every future enrolment rather than only on test day. The fleet
 * grows and phones get replaced; the trial is the first sample, not the only
 * one.
 */
enum class EnrolmentStep(val wire: String, val budgetSeconds: Int) {
    CODE("E1", budgetSeconds = 60),
    PERMISSIONS("E2", budgetSeconds = 180),
    OEM_STEPS("E3", budgetSeconds = 120),
    SIM("E4", budgetSeconds = 30),
    VERIFY("E5", budgetSeconds = 60),
    DONE("E6", budgetSeconds = 15),
}

/**
 * Times one step. Uses the monotonic clock, so a step does not appear to take
 * negative time when the phone syncs its clock mid-enrolment
 * (CONVENTIONS.md §6).
 */
class StepTimer {
    private val started = mutableMapOf<EnrolmentStep, Long>()

    fun start(step: EnrolmentStep) {
        started.putIfAbsent(step, Clock.elapsedRealtimeMillis())
    }

    /** Milliseconds since [start], or null when the step was never started. */
    fun finish(step: EnrolmentStep): Long? {
        val from = started.remove(step) ?: return null
        return Clock.elapsedRealtimeMillis() - from
    }
}

/**
 * One row of E2's checklist.
 *
 * Every row carries a **purpose and consequence** sentence, not a permission
 * name: the person reading it is not technical, it is their own phone, and some
 * of these screens are designed by Android to look alarming. "Mikrofon bo'lmasa
 * suhbat yozilmaydi, lekin qo'ng'iroq baribir qayd etiladi" tells them what
 * they lose; "RECORD_AUDIO ruxsati" tells them nothing.
 */
data class PermissionStepUi(
    val capability: Capability,
    /** Uzbek, from `strings.xml`. Resolved by the screen, not stored here. */
    val titleRes: Int,
    val purposeRes: Int,
    /** The runtime permission to request, or null when the step is a settings
     *  screen rather than a dialog (battery exemption, all-files access). */
    val permission: String?,
    /** Skippable without blocking E6 (SPEC §8.2 marks `contacts` *ixtiyoriy*). */
    val optional: Boolean,
)
