package uz.bonvi.call.domain

/**
 * When it is safe to install an update (T82).
 *
 * ═══ Installing an APK kills the process ═══════════════════════════════════
 * That is the whole rule. Two consequences, and they are not equally bad:
 *
 *  • **A restart mid-upload is recoverable.** The queue is on disk, the upload
 *    is resumable, and the server's `client_call_id` upsert makes a replay
 *    indistinguishable from a first write. Nothing is lost — but the drain is
 *    interrupted, so it is still worth waiting for.
 *  • **A restart mid-capture is a lost call.** The recording in progress is
 *    gone, and the call it belonged to is the one thing this product exists to
 *    keep. There is no recovery: the OS call log will show the call happened
 *    and the app will report it with `app_not_running`, which is honest and
 *    still a loss.
 *
 * So an update never installs during a call, full stop, and waits for the queue
 * by preference. `FORCED` exists because a phone that is permanently blocked by
 * a queue it cannot drain (no network for a week) must still be updatable —
 * but even then, never during a call.
 */
object UpdateReadiness {

    enum class Decision {
        INSTALL,

        /** A call is in progress. Never install. This one has no override. */
        WAIT_CALL_IN_PROGRESS,

        /** The queue is draining. Recoverable, but worth waiting for. */
        WAIT_QUEUE_DRAINING,

        /** Nothing to install. */
        NOT_NEEDED,
    }

    /**
     * @param callInProgress any call the detector is tracking, in any state
     *        short of terminal.
     * @param pendingRecords records still to upload.
     * @param forced the update is REQUIRED (below the minimum version), so the
     *        queue no longer blocks it — the phone is being refused anyway.
     */
    fun decide(
        available: Boolean,
        callInProgress: Boolean,
        pendingRecords: Int,
        forced: Boolean,
    ): Decision = when {
        !available -> Decision.NOT_NEEDED

        // No override, ever. A lost call cannot be recovered and an update can
        // always wait five more minutes.
        callInProgress -> Decision.WAIT_CALL_IN_PROGRESS

        pendingRecords > 0 && !forced -> Decision.WAIT_QUEUE_DRAINING

        else -> Decision.INSTALL
    }

    /**
     * Is this build older than what the server offers?
     *
     * Compared on the version **code**, never the name: N34's gate is a
     * numeric floor, and comparing `"1.2.10"` against `"1.2.9"` as strings puts
     * them the wrong way round.
     */
    fun isNewer(availableVersionCode: Int?, installedVersionCode: Int): Boolean =
        availableVersionCode != null && availableVersionCode > installedVersionCode

    /** Below the server's minimum: the gate will refuse this build once its
     *  queue has drained (N34), so the update is not optional. */
    fun isBelowMinimum(minVersionCode: Int, installedVersionCode: Int): Boolean =
        installedVersionCode < minVersionCode
}
