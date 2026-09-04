package uz.bonvi.call.core

import android.os.SystemClock
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/**
 * Time (CONVENTIONS.md §6, N36). Devices lie, so the wire carries three things
 * and the server decides which one orders anything.
 *
 * Two rules, and they are different rules:
 *
 *  - a **wire timestamp** is wall-clock: `System.currentTimeMillis()`, built
 *    here and nowhere else, so `grep -rn "currentTimeMillis" android/` lands on
 *    one file;
 *  - a **duration** is `SystemClock.elapsedRealtime()`, which is monotonic and
 *    survives the user changing the clock in the middle of a call. Subtracting
 *    two wall-clock readings to get a duration is forbidden — it is how a call
 *    ends up with a negative length in the panel.
 */
object Clock {

    /** Working hours and the business calendar are Tashkent (CONVENTIONS §6). */
    val TASHKENT: ZoneId = ZoneId.of("Asia/Tashkent")

    private val WIRE_FORMAT: DateTimeFormatter = DateTimeFormatter.ISO_OFFSET_DATE_TIME

    /** Milliseconds since the epoch, for `device_epoch_ms` on the wire. */
    fun epochMillis(): Long = System.currentTimeMillis()

    /** The device's IANA zone name, sent raw so the server can compute skew. */
    fun timezoneId(): String = ZoneId.systemDefault().id

    /** ISO-8601 with an explicit offset, e.g. `2026-09-04T14:03:11.412+05:00`. */
    fun toWire(epochMillis: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        ZonedDateTime.ofInstant(Instant.ofEpochMilli(epochMillis), zone).format(WIRE_FORMAT)

    /**
     * A monotonic reading for measuring how long something took. Immune to the
     * clock being changed and to NTP stepping it mid-call.
     */
    fun elapsedRealtimeMillis(): Long = SystemClock.elapsedRealtime()

    /** Whole seconds between two [elapsedRealtimeMillis] readings, never
     *  negative — a negative duration is a bug, not data. */
    fun durationSeconds(startElapsedMillis: Long, endElapsedMillis: Long): Int {
        val delta = endElapsedMillis - startElapsedMillis
        return if (delta <= 0L) 0 else (delta / 1000L).toInt()
    }
}
