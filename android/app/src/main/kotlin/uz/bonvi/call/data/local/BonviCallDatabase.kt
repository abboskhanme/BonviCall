package uz.bonvi.call.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import uz.bonvi.call.domain.CallState

/**
 * The local database. One file, one schema version, migrations from version 2
 * onwards — `fallbackToDestructiveMigration` is forbidden here, because the
 * thing it would destroy is the upload queue: calls that happened, were
 * recorded, and had not reached the server yet.
 *
 * T26/T74/T75 add entities. Adding one means bumping [VERSION] and writing a
 * migration in `di/DatabaseModule.kt`.
 */
@Database(
    entities = [
        QueuedCallEntity::class,
        CallSessionEntity::class,
        PendingCallEntity::class,
        DiscardCounterEntity::class,
    ],
    version = BonviCallDatabase.VERSION,
    exportSchema = true,
)
@TypeConverters(CallStateConverter::class)
abstract class BonviCallDatabase : RoomDatabase() {

    abstract fun queuedCallDao(): QueuedCallDao

    abstract fun callSessionDao(): CallSessionDao

    abstract fun pendingCallDao(): PendingCallDao

    companion object {
        const val VERSION: Int = 1
        const val NAME: String = "bonvicall.db"
    }
}

/**
 * [CallState] is stored by NAME, not by ordinal.
 *
 * An ordinal silently re-points every stored row when somebody inserts a state
 * in the middle of the enum, and what it would re-point here is a queue of
 * calls that have not reached the server. An unknown name resolves to
 * [CallState.IDLE], which the resume pass treats as "start again" rather than
 * crashing on a row written by a newer build.
 */
class CallStateConverter {
    @TypeConverter
    fun toName(state: CallState): String = state.name

    @TypeConverter
    fun fromName(name: String): CallState =
        CallState.entries.firstOrNull { it.name == name } ?: CallState.IDLE
}
