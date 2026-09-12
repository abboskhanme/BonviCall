package uz.bonvi.call.capture

import timber.log.Timber
import uz.bonvi.call.domain.AudioMissingReason
import uz.bonvi.call.domain.CaptureRoute
import java.io.File

/**
 * Picks a capture route and RECORDS WHICH ONE WON (SPEC §7.3, T71a).
 *
 * ═══ The ordering rule, and why it is not "first supported wins" ═══════════
 *
 * The two routes are not the same shape in time:
 *
 *  • `OemHarvestStrategy` is **post-hoc**. The handset's own recorder is
 *    already running or it is not; `start()` only fixes the time window, and
 *    `stop()` looks for a file afterwards — the OEM writer flushes late, which
 *    is why the locator retries.
 *  • `MediaRecorderStrategy` is **live**. It must be running during the call or
 *    there is nothing to collect at the end.
 *
 * You therefore cannot know which route will succeed until the call is over.
 * So every supported strategy is STARTED, and at [stop] the first one in
 * PREFERENCE ORDER that actually produced a file wins. The app's own recording
 * runs as insurance and is discarded when the OEM file exists.
 *
 * That is CallSentry's behaviour — `CtiForegroundService.onIdle()` tries them
 * in order and prefers the OEM file — and S1 confirmed the ordering is correct:
 * the handset's own recorder is what captures both voices.
 *
 * ═══ Per-call reporting ════════════════════════════════════════════════════
 *
 * [Outcome.attempts] carries one row per strategy: its route and what happened.
 * The panel stores `capture_route` for the winner, but the gap report needs to
 * know that the OEM route was TRIED and returned nothing, which is a different
 * fact from it never having been available (SPEC §5.2, UC-23).
 */
class CaptureRouter(private val strategies: List<RecordingStrategy>) {

    /** What one strategy did during one call. */
    data class Attempt(
        val route: CaptureRoute,
        val started: Boolean,
        val producedFile: Boolean,
        val reason: AudioMissingReason?,
    )

    /**
     * The result of one call's capture. Never an exception: a failure here is
     * data — a reason on a call that is uploaded regardless (UC-14).
     */
    data class Outcome(
        val file: File?,
        val route: CaptureRoute,
        val reason: AudioMissingReason?,
        val attempts: List<Attempt>,
    ) {
        val hasAudio: Boolean get() = file != null

        init {
            // The two fields the panel reads must never disagree: a call with a
            // file and a reason, or without a file and without one, is a row
            // nobody can interpret.
            require((file == null) == (reason != null)) {
                "Outcome must carry exactly one of file or reason"
            }
        }
    }

    private val running = mutableListOf<RecordingStrategy>()
    private val skipped = mutableListOf<Attempt>()

    /**
     * Start every supported strategy.
     *
     * [targetFor] gives each strategy its OWN destination. Two strategies
     * writing one path is how a fallback silently truncates the preferred
     * route's output, and the failure looks like a corrupt recording rather
     * than a bug.
     */
    fun start(targetFor: (RecordingStrategy) -> File) {
        running.clear()
        skipped.clear()
        for (strategy in strategies) {
            if (!strategy.isSupported()) {
                skipped += Attempt(
                    route = strategy.route,
                    started = false,
                    producedFile = false,
                    reason = strategy.lastFailure()
                        ?: AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE,
                )
                continue
            }
            @Suppress("TooGenericExceptionCaught")
            try {
                strategy.start(targetFor(strategy))
                running += strategy
            } catch (error: Exception) {
                // Broad on purpose, and this is the specific failure it catches:
                // a recorder that refuses to start (device busy, another app
                // holding the microphone, an OEM that revoked the permission
                // silently). It must degrade to "no audio, with a reason" and
                // never take the call down with it — UC-14.
                Timber.w(error, "Strategy %s failed to start", strategy.route.wire)
                skipped += Attempt(
                    route = strategy.route,
                    started = false,
                    producedFile = false,
                    reason = strategy.lastFailure() ?: AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE,
                )
            }
        }
    }

    /** Stop everything and return the winner in preference order. */
    fun stop(): Outcome {
        val attempts = mutableListOf<Attempt>()
        var winnerFile: File? = null
        var winnerRoute: CaptureRoute? = null

        // LIVE recorders stop first. A post-hoc strategy polls for seconds at
        // stop(); a microphone still running through that poll records the
        // employee after the call. `sortedBy` is stable, so the preference
        // order among the live ones is kept.
        val produced = LinkedHashMap<RecordingStrategy, File?>()
        for (strategy in running.sortedBy { it.postHoc }) {
            @Suppress("TooGenericExceptionCaught")
            val file = try {
                strategy.stop()
            } catch (error: Exception) {
                // Same reasoning as start(): a recorder that throws on stop
                // (already released, storage full mid-write) yields a reason,
                // never a lost call.
                Timber.w(error, "Strategy %s failed to stop", strategy.route.wire)
                null
            }
            produced[strategy] = file
            attempts += Attempt(
                route = strategy.route,
                started = true,
                producedFile = file != null,
                reason = if (file == null) {
                    strategy.lastFailure() ?: AudioMissingReason.CAPTURE_RETURNED_SILENCE
                } else {
                    null
                },
            )
        }
        // The WINNER is still chosen in preference order — the order of
        // `strategies`, which `running` preserves — whatever order they were
        // stopped in.
        for (strategy in running) {
            val file = produced[strategy] ?: continue
            winnerFile = file
            winnerRoute = strategy.route
            break
        }

        val allAttempts = orderAttempts(attempts + skipped)
        running.clear()
        skipped.clear()

        return if (winnerFile != null && winnerRoute != null) {
            Outcome(winnerFile, winnerRoute, reason = null, attempts = allAttempts)
        } else {
            Outcome(
                file = null,
                route = CaptureRoute.NONE,
                reason = summarise(allAttempts),
                attempts = allAttempts,
            )
        }
    }

    /** Attempts in the router's own preference order, so the report reads the
     *  same way the routing did. */
    private fun orderAttempts(attempts: List<Attempt>): List<Attempt> {
        val order = strategies.map { it.route }
        return attempts.sortedBy { attempt ->
            order.indexOf(attempt.route).takeIf { it >= 0 } ?: Int.MAX_VALUE
        }
    }

    /**
     * One reason for a call that got no audio.
     *
     * The PREFERRED route's reason wins. It is the one that explains the
     * failure: "the handset's own recorder is switched off" is what an admin
     * has to act on, and "the app's microphone fallback also returned silence"
     * is a consequence of it.
     */
    private fun summarise(attempts: List<Attempt>): AudioMissingReason =
        attempts.firstNotNullOfOrNull { it.reason }
            ?: AudioMissingReason.RECORDING_ROUTE_UNAVAILABLE
}
