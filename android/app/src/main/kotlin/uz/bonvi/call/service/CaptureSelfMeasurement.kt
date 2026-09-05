package uz.bonvi.call.service

import timber.log.Timber
import uz.bonvi.call.core.Clock
import uz.bonvi.call.data.local.PendingCallDao
import uz.bonvi.call.data.remote.api.DeviceCallsApi
import uz.bonvi.call.data.remote.dto.DeviceCallLogDeltaIn
import java.time.Instant
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The self-measurement sweep (T70, UC-13, SPEC §4.4).
 *
 * ═══ Why this exists at all ════════════════════════════════════════════════
 * These are the employees' own phones. Nobody can `adb` into them, nobody will
 * hand one over for an afternoon, and the fleet is spread across a city. **This
 * is the only production capture-rate metric the product gets**: the device
 * counts what its own call log says happened, compares it with what it
 * uploaded, and reports the difference per day.
 *
 * Without it, "the panel shows 40 calls" and "the phone made 40 calls" are two
 * unrelated statements and nobody can tell a quiet week from a broken handset.
 * With it, the gap is a number with a reason attached.
 *
 * The counts include the calls the privacy boundary **discarded**, which is the
 * part that makes the number honest: a phone that captured nothing because
 * every call was on the personal SIM is working correctly, and a phone that
 * captured nothing because the subscription could not be identified is not.
 * Reporting only "captured" would make those two look identical.
 *
 * It sends counts, never call data. A discarded call contributes 1 to a counter
 * and nothing else — no number, no time, no duration (N28).
 */
@Singleton
class CaptureSelfMeasurement @Inject constructor(
    private val callLog: CallLogReader,
    private val pendingDao: PendingCallDao,
    private val api: DeviceCallsApi,
) {

    data class Delta(
        val day: String,
        val inCallLog: Int,
        val captured: Int,
        val discarded: Int,
    ) {
        /** Calls the log knows about that the app neither captured nor
         *  deliberately discarded. This is the number that means something is
         *  wrong, and it is the one the gap report acts on. */
        val unexplained: Int get() = (inCallLog - captured - discarded).coerceAtLeast(0)
    }

    suspend fun measureAndReport(sinceEpochMillis: Long): Delta? {
        val entries = callLog.since(sinceEpochMillis)
        if (entries.isEmpty()) {
            // Either a genuinely quiet period or a call log the app cannot
            // read. The capability check reports which; the sweep does not
            // guess, and it does NOT report a delta it cannot stand behind.
            Timber.i("Self-measurement: no call-log rows in the window")
            return null
        }

        val day = DAY.format(
            Instant.ofEpochMilli(Clock.epochMillis()).atZone(Clock.TASHKENT),
        )
        val discarded = pendingDao.discardTotalFor(day)
        val todayStart = entries.filter { sameDay(it.startedAtEpochMillis, day) }
        val delta = Delta(
            day = day,
            inCallLog = todayStart.size,
            // Everything in the log that was not discarded should have been
            // captured; the server holds the authoritative captured count and
            // computes the difference. The device reports what it saw.
            captured = (todayStart.size - discarded).coerceAtLeast(0),
            discarded = discarded,
        )

        @Suppress("TooGenericExceptionCaught")
        try {
            api.reportCallLogDelta(
                DeviceCallLogDeltaIn(
                    periodDate = java.time.LocalDate.parse(delta.day),
                    deviceCounted = delta.inCallLog,
                    uploadedCount = delta.captured,
                    // The count the whole metric turns on: a phone that
                    // captured nothing because every call was on the personal
                    // SIM is working correctly; one that captured nothing
                    // because the subscription could not be identified is not.
                    subscriptionUnknownCount = delta.discarded,
                    sweptAt = java.time.OffsetDateTime.parse(
                        Clock.toWire(Clock.epochMillis()),
                    ),
                ),
            )
        } catch (error: Exception) {
            // Broad, and the specific failure is no network — the normal case
            // for a phone in the field. Measurement must never take down the
            // sweep that recovers actual calls.
            Timber.i("Could not report the call-log delta; it will be resent")
        }
        return delta
    }

    private fun sameDay(epochMillis: Long, day: String): Boolean =
        DAY.format(Instant.ofEpochMilli(epochMillis).atZone(Clock.TASHKENT)) == day

    private companion object {
        val DAY: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd")
    }
}
