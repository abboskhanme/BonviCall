package uz.bonvi.call.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

/**
 * A call in flight, and the day's discard counters.
 *
 * Both survive process death, and both have to: the foreground service is
 * killed between a call's edges on any handset with an aggressive battery
 * manager, and a counter kept in memory would reset every time — which would
 * make the fleet's `subscription_unknown` rate read as zero, the one number
 * that must not be quietly wrong (SPEC §7.4).
 */
@Entity(tableName = "pending_calls")
data class PendingCallEntity(
    @PrimaryKey val callId: String,
    val direction: String,
    val remoteNumber: String?,
    val registeredNumber: String,
    val subscriptionId: Int,
    val startedAtEpochMillis: Long,
    val startedElapsedMillis: Long,
    val answeredAtEpochMillis: Long?,
    val endedAtEpochMillis: Long?,
)

/**
 * Calls the privacy boundary refused, counted per day and per reason.
 *
 * **Only the count exists** — no number, no time, no duration. A rejected call
 * is one we have decided is not ours, so storing anything identifying about it
 * would defeat the decision (N28). The counts are reported in the call-log
 * delta so the gap report can show them (SPEC §4.4), which is what turns
 * "the app captured nothing today" from a silence into a number.
 */
@Entity(tableName = "discard_counters", primaryKeys = ["day", "reason"])
data class DiscardCounterEntity(
    /** `yyyy-MM-dd` in Asia/Tashkent — the business day the report groups by. */
    val day: String,
    val reason: String,
    val count: Int,
)

@Dao
interface PendingCallDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(call: PendingCallEntity)

    @Query("SELECT * FROM pending_calls WHERE callId = :callId")
    suspend fun find(callId: String): PendingCallEntity?

    @Query("SELECT * FROM pending_calls ORDER BY startedAtEpochMillis ASC")
    suspend fun all(): List<PendingCallEntity>

    @Query("DELETE FROM pending_calls WHERE callId = :callId")
    suspend fun delete(callId: String)

    /** Calls whose end was never seen — the process died mid-call. They are
     *  reconciled from the call log rather than dropped (UC-13). */
    @Query("SELECT * FROM pending_calls WHERE endedAtEpochMillis IS NULL AND startedAtEpochMillis < :before")
    suspend fun abandonedBefore(before: Long): List<PendingCallEntity>

    @Query(
        "INSERT INTO discard_counters (day, reason, count) VALUES (:day, :reason, 1) " +
            "ON CONFLICT(day, reason) DO UPDATE SET count = count + 1",
    )
    suspend fun incrementDiscard(day: String, reason: String)

    @Query("SELECT * FROM discard_counters WHERE day = :day")
    suspend fun discardsFor(day: String): List<DiscardCounterEntity>

    @Query("SELECT COALESCE(SUM(count), 0) FROM discard_counters WHERE day = :day")
    suspend fun discardTotalFor(day: String): Int
}
