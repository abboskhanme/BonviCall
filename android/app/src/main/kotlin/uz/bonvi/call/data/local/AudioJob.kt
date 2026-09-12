package uz.bonvi.call.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query

/**
 * A recording waiting to be transcoded and uploaded (T73, T74, N8).
 *
 * ═══ Why the file path is not enough ═══════════════════════════════════════
 * The recording exists on disk the moment the call ends, but it cannot be
 * uploaded then: the server accepts audio only against a call it already has,
 * and `client_call_id` is derived from the call log's own timestamp by the
 * reconciliation sweep twenty seconds later (§3.10 rule 1). So the sweep writes
 * a row here, and the upload worker drains it once the call's metadata has been
 * confirmed.
 *
 * ═══ Why it is a table and not a field on the queue row ════════════════════
 * The metadata row is deleted the moment the server confirms it (N11). The
 * audio outlives it — a twenty-minute recording on a weak connection takes
 * several passes — and a row that is deleted while its file still needs
 * uploading is a recording nobody ever asks for again.
 *
 * The capture route travels with it because it decides whether the source file
 * may be **deleted**: an OEM-harvested file is the employee's own recording in
 * their own folder and is never touched (CONVENTIONS.md §8.3).
 */
@Entity(tableName = "audio_jobs")
data class AudioJobEntity(
    /** The call this audio belongs to. One recording per call. */
    @PrimaryKey val clientCallId: String,
    val path: String,
    /** `CaptureRoute.wire`. Decides whether the source file is ours to delete. */
    val captureRoute: String,
    val recordedAtEpochMillis: Long,
    val queuedAtEpochMillis: Long,
    val attempts: Int = 0,
    val lastErrorCode: String? = null,
)

@Dao
interface AudioJobDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(job: AudioJobEntity)

    /** Oldest first: a phone that has been offline uploads the call it made
     *  first, which is the one somebody is most likely to be asking about. */
    @Query("SELECT * FROM audio_jobs ORDER BY recordedAtEpochMillis ASC LIMIT :limit")
    suspend fun next(limit: Int): List<AudioJobEntity>

    @Query("DELETE FROM audio_jobs WHERE clientCallId = :clientCallId")
    suspend fun delete(clientCallId: String)

    @Query(
        "UPDATE audio_jobs SET attempts = attempts + 1, lastErrorCode = :code " +
            "WHERE clientCallId = :clientCallId",
    )
    suspend fun recordAttempt(clientCallId: String, code: String?)

    @Query("SELECT COUNT(*) FROM audio_jobs")
    suspend fun count(): Int
}
