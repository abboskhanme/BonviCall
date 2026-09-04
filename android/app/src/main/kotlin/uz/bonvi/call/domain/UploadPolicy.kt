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

        val index = (attempt - 1).coerceIn(0, BACKOFF_SECONDS.lastIndex)
        return Outcome.Retry(attempt, BACKOFF_SECONDS[index])
    }

    /** True when this row should be handed to the network at all. */
    fun isSendable(attempts: Int, parked: Boolean): Boolean =
        !parked && attempts < MAX_ATTEMPTS

    private const val TOO_MANY_REQUESTS = 429
    private const val REQUEST_TIMEOUT = 408
    private const val VERSION_UNSUPPORTED = "app_version_unsupported"
}
