package uz.bonvi.call.domain

/**
 * Matching a live-captured call to its call-log row (T67, UC-13, SPEC §3.10).
 *
 * Pure, because this is the rule that decides whether a call is uploaded once
 * or twice, and N2 puts the acceptable duplicate rate at 0.
 *
 * The live capture and the log disagree about the start time by up to a second
 * or two — the log records when the platform committed the row, the service
 * records when it saw the edge — so the match is a window, not an equality.
 * Direction and the remote number's 9-digit key must agree; a window alone
 * would pair two calls made a second apart to the wrong rows.
 */
object ReconcileRule {

    /**
     * How far apart a live start time and a call-log `DATE` may be and still be
     * the same call. Two seconds: measured drift is under one, and doubling it
     * costs nothing because direction and number must also match.
     */
    const val MATCH_WINDOW_MS: Long = 2_000L

    data class Candidate(
        val startedAtEpochMillis: Long,
        val direction: CallDirection,
        val remoteNumber: String?,
    )

    /**
     * The call-log entry that is this call, or null.
     *
     * Null is a normal answer: the log row can lag the call by minutes, which
     * is why §3.10 rule 2 gives it fifteen before deriving the id from the live
     * time and marking the record unreconciled.
     */
    fun <T> match(
        live: Candidate,
        entries: List<T>,
        startedAt: (T) -> Long,
        direction: (T) -> CallDirection,
        remoteNumber: (T) -> String?,
    ): T? = entries
        .filter { direction(it) == live.direction }
        .filter { sameNumber(remoteNumber(it), live.remoteNumber) }
        .filter { kotlin.math.abs(startedAt(it) - live.startedAtEpochMillis) <= MATCH_WINDOW_MS }
        // The closest in time, so two calls to the same number a second apart
        // pair with their own rows rather than both with the first.
        .minByOrNull { kotlin.math.abs(startedAt(it) - live.startedAtEpochMillis) }

    /**
     * Two numbers are the same call's number when their 9-digit keys agree.
     *
     * Both unknown counts as agreement — a withheld caller id is withheld in
     * the log too, and refusing to match there would upload every anonymous
     * call twice: once unreconciled, once by the recovery sweep.
     *
     * ⚠️ **A live side that knows no number matches anything.** This was
     * `logKey == liveKey`, which is right only while the live source can see
     * numbers — and from API 31 it cannot: `TelephonyCallback.CallStateListener`
     * reports a state and nothing else, so the live number is *always* null on
     * every handset in this fleet. The log has the number, so the keys never
     * agreed and **every live-detected call failed to reconcile**, waited out
     * the fifteen minutes and then arrived as an unreconciled duplicate of a
     * row the recovery sweep had already written.
     *
     * Measured on a Xiaomi 13 Lite, 2026-09-11: the call was detected live,
     * recorded, and still reached the server as `call_log_recovery` with
     * `app_not_running`.
     *
     * Null from the live side means "we were not told", not "it was withheld",
     * and those are different facts. Direction plus a two-second window is
     * what identifies the call then — and `match` still takes the closest in
     * time, so two calls inside one window pair with their own rows.
     */
    private fun sameNumber(fromLog: String?, fromLive: String?): Boolean {
        val liveKey = uz.bonvi.call.core.Phone.phoneKey(fromLive)
        if (liveKey == null) return true
        return uz.bonvi.call.core.Phone.phoneKey(fromLog) == liveKey
    }

    /** §3.10 rule 2: after this long with no matching row, derive the id from
     *  the live start time and set `reconciled_with_call_log = false`. */
    fun deadlinePassed(callEndedAtEpochMillis: Long, nowEpochMillis: Long): Boolean =
        nowEpochMillis - callEndedAtEpochMillis >= ClientCallId.RECONCILE_DEADLINE_MS
}
