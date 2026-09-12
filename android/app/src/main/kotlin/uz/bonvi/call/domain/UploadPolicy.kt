package uz.bonvi.call.domain

/**
 * What the upload queue does with a failure (N8, CONVENTIONS-CLIENT.md §9).
 *
 * Pure, and separate from Room on purpose: "how many times do we retry and what
 * happens then" is a rule, and a rule that can only be tested by writing rows
 * to a database is a rule nobody tests.
 *
 * Three things it encodes, each of which the product would be worse without:
 *
 *  1. **Oldest first.** A newer call must never overtake an older one.
 *  2. **Parked, never deleted.** After [MAX_ATTEMPTS] a row stops being retried
 *     and is REPORTED. Deleting it makes the failure invisible, and an
 *     invisible failure here is a call that never existed.
 *  3. **A 4xx is not a retry.** Replaying a request the server has already
 *     judged just burns the employee's data allowance against N15's cap.
 */
object UploadPolicy {

    /** N8: five attempts, then park and report. */
    const val MAX_ATTEMPTS: Int = 5

    /**
     * The request never reached a server at all.
     *
     * ⚠️ **This must never park a row, at any attempt count.** An unreachable
     * server is a fact about the network — a phone in a lift, a laptop asleep,
     * a tunnel that dropped — and not a judgement on the call. Treating it as
     * one of the five attempts is what put 39 real calls on a live handset
     * into a permanent parked state that nothing would ever retry: the backoff
     * reaches attempt five after about 1 h 45 m offline, so any outage longer
     * than an afternoon silently killed the entire queue.
     *
     * `CallUploader` passes this code for the no-response case, which is
     * deliberately distinct from `payload_unreadable` — that one is also
     * `status = 0` and *must* park, because a row that cannot be parsed can
     * never succeed and would block the queue behind it for ever.
     */
    const val UNREACHABLE: String = "server_unreachable"

    /** Backoff, in seconds, indexed by attempt count. Capped rather than
     *  unbounded: a phone that comes back after a week should drain that week's
     *  calls promptly, not wait an hour between them. */
    private val BACKOFF_SECONDS = listOf(30L, 120L, 600L, 1_800L, 3_600L)

    sealed interface Outcome {
        /** Try again after [afterSeconds]. */
        data class Retry(val attempt: Int, val afterSeconds: Long) : Outcome

        /** Stop trying. The row STAYS and is reported on the next heartbeat. */
        data class Park(val reason: String) : Outcome

        /** The server has it. Delete the row — and only now (N11: local audio
         *  is deleted only after the server confirms the checksum). */
        data object Confirmed : Outcome
    }

    /**
     * @param attemptsSoFar attempts already recorded, before this failure.
     * @param status the HTTP status, or 0 when the request never reached a
     *        server.
     * @param code the envelope's error code, or null.
     */
    fun onFailure(attemptsSoFar: Int, status: Int, code: String?): Outcome {
        val attempt = attemptsSoFar + 1

        // Before every other rule, including the attempt limit: nothing that
        // never reached a server may be parked. The attempt is still counted,
        // so the backoff keeps widening and the panel can see how long a
        // handset has been shouting into nothing — it just never becomes
        // permanent. See [UNREACHABLE].
        if (code == UNREACHABLE) {
            return Outcome.Retry(attempt, backoffFor(attempt))
        }

        // 426 is special and the order is the rule (CONVENTIONS.md §4.4): an
        // app below the minimum version is refused only AFTER its queue has
        // drained, so if we ever see it on an ingest call the right answer is
        // to park and report, never to drop. Refusing an old client must not
        // destroy data.
        if (code == VERSION_UNSUPPORTED) return Outcome.Park(code)

        // A 4xx the server has already judged. Retrying changes nothing and
        // costs the employee's data.
        if (status in 400..499 && status != TOO_MANY_REQUESTS && status != REQUEST_TIMEOUT) {
            return Outcome.Park(code ?: "http_$status")
        }

        if (attempt >= MAX_ATTEMPTS) return Outcome.Park(code ?: "max_attempts")

        return Outcome.Retry(attempt, backoffFor(attempt))
    }

    /** The wait before attempt [attempt], capped at the last step so a handset
     *  that has been offline for a week still drains that week promptly rather
     *  than waiting longer and longer for ever. */
    private fun backoffFor(attempt: Int): Long =
        BACKOFF_SECONDS[(attempt - 1).coerceIn(0, BACKOFF_SECONDS.lastIndex)]

    // `isSendable(attempts, parked)` was here with no production caller. It is
    // not a missing wiring: [onFailure] parks a row the moment it reaches
    // [MAX_ATTEMPTS], so "not parked" already means "under the limit", and the
    // DAO's `WHERE parkedAtEpochMillis IS NULL` is the same rule expressed
    // where the rows are. Two spellings of one rule is how they drift.

    private const val TOO_MANY_REQUESTS = 429
    private const val REQUEST_TIMEOUT = 408
    private const val VERSION_UNSUPPORTED = "app_version_unsupported"
}
