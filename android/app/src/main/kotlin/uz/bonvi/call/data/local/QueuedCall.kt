package uz.bonvi.call.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import uz.bonvi.call.domain.UploadPolicy

/**
 * Room is the queue of record (N8, CONVENTIONS-CLIENT.md §9).
 *
 * The rules are in `domain/UploadPolicy.kt`, pure and tested; this file is the
 * storage that obeys them. Three properties the whole upload path depends on
 * are enforced by the SCHEMA rather than by the code that uses it:
 *
 *  1. **`clientCallId` is unique.** It is the idempotency key of
 *     CONVENTIONS.md §5 — a UUID generated on the device, carried in the BODY
 *     so it survives an app restart and retry plumbing that drops headers. The
 *     unique index is what turns a retry storm into one row instead of nine.
 *  2. **Oldest first**, with the id as tiebreak, so two calls queued in the
 *     same millisecond still have a stable order.
 *  3. **Parked rows stay.** There is no "delete failed rows" query in this DAO
 *     and there must not be one. [deleteConfirmed] is the only delete, and it
 *     runs after the server has acknowledged.
 */
@Entity(
    tableName = "queued_calls",
    indices = [
        Index(value = ["clientCallId"], unique = true),
        Index(value = ["queuedAtEpochMillis"]),
    ],
)
data class QueuedCallEntity(
    @PrimaryKey val clientCallId: String,
    /** The serialised `CallRecord`, written once at enqueue time. */
    val payloadJson: String,
    val queuedAtEpochMillis: Long,
    val attempts: Int = 0,
    /** Set when the row is parked. The row is never deleted because of it. */
    val parkedAtEpochMillis: Long? = null,
    /** The envelope code or transport reason that parked it, for the report. */
    val lastErrorCode: String? = null,
    val nextAttemptAtEpochMillis: Long = 0L,
) {
    val isParked: Boolean get() = parkedAtEpochMillis != null

    companion object {
        /** Mirrors [UploadPolicy.MAX_ATTEMPTS]; a test asserts they agree, so
         *  the number is decided in one place. */
        const val MAX_ATTEMPTS: Int = UploadPolicy.MAX_ATTEMPTS
    }
}

@Dao
interface QueuedCallDao {

    /**
     * The next rows to send: oldest first, parked rows excluded, and nothing
     * whose backoff has not elapsed.
     */
    @Query(
        "SELECT * FROM queued_calls " +
            "WHERE parkedAtEpochMillis IS NULL AND nextAttemptAtEpochMillis <= :nowEpochMillis " +
            "ORDER BY queuedAtEpochMillis ASC, clientCallId ASC LIMIT :limit",
    )
    suspend fun nextBatch(nowEpochMillis: Long, limit: Int): List<QueuedCallEntity>

    /**
     * IGNORE, not REPLACE.
     *
     * The client id is the idempotency key: a second enqueue of the same call
     * is a retry, and REPLACE would reset its attempt count and let a poisoned
     * row loop forever. Returns -1 when the row already existed.
     */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun enqueue(call: QueuedCallEntity): Long

    @Query(
        "UPDATE queued_calls SET attempts = attempts + 1, " +
            "lastErrorCode = :errorCode, nextAttemptAtEpochMillis = :nextAttemptAtEpochMillis " +
            "WHERE clientCallId = :clientCallId",
    )
    suspend fun recordAttempt(
        clientCallId: String,
        errorCode: String?,
        nextAttemptAtEpochMillis: Long,
    )

    /** Stop retrying. The row stays and is reported. */
    @Query(
        "UPDATE queued_calls SET attempts = attempts + 1, " +
            "parkedAtEpochMillis = :parkedAtEpochMillis, lastErrorCode = :errorCode " +
            "WHERE clientCallId = :clientCallId",
    )
    suspend fun park(clientCallId: String, parkedAtEpochMillis: Long, errorCode: String?)

    /**
     * Give back the rows that were parked only because nobody answered.
     *
     * Called when the server is demonstrably reachable again. Rows parked by a
     * JUDGEMENT — a 4xx, an unreadable payload, a refused version — are left
     * exactly where they are: the server has already ruled on those and
     * retrying burns the employee's data for nothing. Only the two codes that
     * mean "we never got through" come back, and their attempt count is reset
     * so they get a full run rather than one last try.
     */
    @Query(
        "UPDATE queued_calls SET parkedAtEpochMillis = NULL, attempts = 0, " +
            "nextAttemptAtEpochMillis = :nowEpochMillis " +
            "WHERE parkedAtEpochMillis IS NOT NULL " +
            "AND lastErrorCode IN ('max_attempts', 'server_unreachable')",
    )
    suspend fun unparkUnreachable(nowEpochMillis: Long): Int

    /** The only delete in this DAO, and it runs only after the server has the
     *  row (N11). */
    @Query("DELETE FROM queued_calls WHERE clientCallId = :clientCallId")
    suspend fun deleteConfirmed(clientCallId: String)

    @Query("SELECT COUNT(*) FROM queued_calls WHERE parkedAtEpochMillis IS NULL")
    suspend fun pendingCount(): Int

    /** Reported on every heartbeat, so the panel shows queue depth and the
     *  parked rows are visible instead of silently absent (SPEC §5.2). */
    @Query("SELECT COUNT(*) FROM queued_calls WHERE parkedAtEpochMillis IS NOT NULL")
    suspend fun parkedCount(): Int

    @Query("SELECT COALESCE(SUM(LENGTH(payloadJson)), 0) FROM queued_calls")
    suspend fun queuedBytes(): Long
}
