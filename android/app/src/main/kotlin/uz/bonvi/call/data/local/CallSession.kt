package uz.bonvi.call.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import uz.bonvi.call.domain.CallState

/**
 * One in-flight call's state, persisted on every transition (SPEC §7.5).
 *
 * The point is process death. The foreground service can be killed between a
 * call ending and its audio being queued — that is the normal case on a phone
 * with an aggressive OEM battery manager, which is most of the fleet. On the
 * next start the service RESUMES from these rows rather than restarting, so a
 * call that was mid-reconciliation is finished instead of lost.
 *
 * Keyed by the platform call id, not by a row id: SPEC §7.5's call-waiting rule
 * needs a **separate machine instance per call**, and the prototype's failure to
 * do that is R5.
 */
@Entity(
    tableName = "call_sessions",
    indices = [Index(value = ["updatedAtEpochMillis"])],
)
data class CallSessionEntity(
    @PrimaryKey val callId: String,
    val state: CallState,
    /** The client-generated idempotency key, assigned once the call is
     *  attributed. Null while the machine is still in IDENTIFYING. */
    val clientCallId: String? = null,
    val updatedAtEpochMillis: Long,
)

@Dao
interface CallSessionDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(session: CallSessionEntity)

    @Query("SELECT * FROM call_sessions WHERE callId = :callId")
    suspend fun find(callId: String): CallSessionEntity?

    /**
     * Everything not finished, for the resume pass on service start.
     * COMPLETE and DISCARDED rows are removed as they are reached, so this is
     * the whole working set.
     */
    @Query("SELECT * FROM call_sessions ORDER BY updatedAtEpochMillis ASC")
    suspend fun all(): List<CallSessionEntity>

    @Query("DELETE FROM call_sessions WHERE callId = :callId")
    suspend fun delete(callId: String)
}
