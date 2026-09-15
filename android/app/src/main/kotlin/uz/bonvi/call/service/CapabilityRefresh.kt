package uz.bonvi.call.service

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import timber.log.Timber
import uz.bonvi.call.data.session.CapabilitySnapshotStore
import uz.bonvi.call.data.session.SessionStore
import uz.bonvi.call.domain.Capability
import uz.bonvi.call.domain.CapabilityDelta
import uz.bonvi.call.domain.CaptureReadiness
import uz.bonvi.call.domain.CapabilityResult
import uz.bonvi.call.enrolment.CapabilityChecks
import uz.bonvi.call.enrolment.EnrolmentRepository
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Notice a permission that was granted (or taken away) AFTER enrolment.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * The gap this closes, seen on a real handset on 2026-09-15:
 *
 * An agent skipped "all files access" during enrolment, so the OEM recording
 * folder was unreadable and every call was captured by the app's own
 * microphone instead — which on Android 13 hands back pure silence during a
 * call. The permission was then granted from the system settings, and capture
 * started working immediately. **The panel went on saying "Ruxsat berilmagan"**
 * for as long as anybody cared to look, because capabilities were reported in
 * exactly two moments: during enrolment, and when an admin sent a `recheck`
 * command.
 *
 * So the panel's most important screen — "what is stopping this phone" —
 * described the day the app was installed, not the phone in front of you. An
 * agent who fixes their own permission has no way to make the panel agree, and
 * the admin watching the rollout is told to chase a problem that is gone.
 *
 * ═══ What runs, and what deliberately does not ═════════════════════════════
 *
 * [E2_WITHOUT_MICROPHONE] is every check except the microphone. The microphone
 * probe is a real one-second `AudioRecord` capture (SPEC §7.8), and on Android
 * 12+ any capture lights the green microphone indicator. Running that on a
 * schedule, on a phone the employee owns, would put a recording dot on their
 * screen every fifteen minutes for a check nobody asked for — and it could
 * collide with a live call. It stays where it belongs: enrolment, and the
 * explicit `recheck` an admin sends ([full]).
 *
 * ═══ Reported only when something CHANGED ══════════════════════════════════
 *
 * The snapshot in [CapabilitySnapshotStore] is what makes this affordable
 * every fifteen minutes and on every app open: a phone whose permissions have
 * not moved sends nothing at all. `checked_at` on the server therefore keeps
 * meaning "when this state was last true", not "when the phone last woke up".
 * ═══════════════════════════════════════════════════════════════════════════
 */
@Singleton
class CapabilityRefresh @Inject constructor(
    private val checks: CapabilityChecks,
    private val enrolment: EnrolmentRepository,
    private val session: SessionStore,
    private val snapshots: CapabilitySnapshotStore,
) {

    /** Serialises the app-open pass against the heartbeat's. */
    private val lock = Mutex()

    /**
     * Re-run the cheap checks; report only what moved.
     *
     * Returns the results that were reported, empty when nothing changed or
     * the phone is not enrolled. Never throws: this runs beside a heartbeat
     * and behind an Activity's `onStart`, and neither has anywhere to put an
     * exception.
     */
    suspend fun ifChanged(reason: String): List<CapabilityResult> = lock.withLock {
        if (session.snapshot.installationId == null) return emptyList()

        val results = E2_WITHOUT_MICROPHONE.map { checks.check(it) }
        val changed = CapabilityDelta.changed(snapshots.last(), results)
        if (changed.isEmpty()) return emptyList()

        Timber.i("Capabilities changed (%s): %s", reason, changed.joinToString { it.capability.wire })
        return when (enrolment.reportCapabilities(changed)) {
            is EnrolmentRepository.Result.Ok -> {
                // Stored only after the server has it. A report that failed to
                // land must be sent again next time, or the phone would go on
                // believing the panel knows something it does not.
                snapshots.remember(CapabilityDelta.snapshotOf(results))
                changed
            }

            else -> emptyList()
        }
    }

    /**
     * Every E2 check, microphone included, reported whatever it says.
     *
     * The `recheck` command's body: an admin pressing it has decided the cost
     * of a one-second capture is worth an answer, and is entitled to one even
     * when nothing has changed.
     */
    suspend fun full(): Report = lock.withLock {
        val results = CaptureReadiness.E2_ORDER.map { checks.check(it) }
        val reported = enrolment.reportCapabilities(results) is EnrolmentRepository.Result.Ok
        if (reported) {
            snapshots.remember(CapabilityDelta.snapshotOf(results))
        }
        return Report(results, reported)
    }

    /** What the checks found, and whether the server has been told. The screen
     *  needs the first and the command needs the second. */
    data class Report(val results: List<CapabilityResult>, val reported: Boolean)

    private companion object {
        /** E2's order, minus the probe that would light the microphone dot. */
        val E2_WITHOUT_MICROPHONE: List<Capability> =
            CaptureReadiness.E2_ORDER.filterNot { it == Capability.MICROPHONE }
    }
}
