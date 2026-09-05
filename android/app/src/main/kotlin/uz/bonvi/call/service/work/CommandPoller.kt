package uz.bonvi.call.service.work

import uz.bonvi.call.core.Clock
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Whether a command is still worth acting on (T80, UC-16).
 *
 * ═══ Why staleness is a rule and not a detail ══════════════════════════════
 * UC-16's bar is 5 000 ms and the WebSocket hub measures 13 ms, so the
 * transport is not the risk — **doze on MIUI and EMUI is**. A phone that was
 * asleep can receive a ten-minute-old dial command the moment it wakes, and
 * dialling it then is worse than not dialling it at all: somebody answers a
 * call the salesperson has forgotten making, from a number they do not
 * recognise, about a conversation that already happened.
 *
 * So a command older than [MAX_AGE_MS] is **discarded and acknowledged as
 * stale** — acknowledged, not silently dropped, because the panel has to be
 * able to show that the command reached the phone too late rather than never
 * arriving at all. Those are different faults with different fixes.
 */
@Singleton
class CommandFreshness @Inject constructor() {

    /**
     * Two minutes. Long enough to survive a normal doze window and a slow
     * reconnect; short enough that the person on the other end still remembers
     * the context. UC-16's own bar is 5 s — this is the outer limit of "late
     * but still useful", not the target.
     */
    fun isFresh(issuedAtEpochMillis: Long, nowEpochMillis: Long = Clock.epochMillis()): Boolean =
        nowEpochMillis - issuedAtEpochMillis <= MAX_AGE_MS

    /** How a stale command is reported, so the panel can tell "arrived late"
     *  from "never arrived". */
    fun stalenessReason(issuedAtEpochMillis: Long, nowEpochMillis: Long): String =
        "discarded_stale_${(nowEpochMillis - issuedAtEpochMillis) / 1000}s"

    companion object {
        const val MAX_AGE_MS: Long = 2 * 60 * 1000L
    }
}
