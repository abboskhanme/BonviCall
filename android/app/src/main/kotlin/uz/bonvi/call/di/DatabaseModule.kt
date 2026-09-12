package uz.bonvi.call.di

import android.content.Context
import androidx.room.Room
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.data.local.AudioJobDao
import uz.bonvi.call.data.local.BonviCallDatabase
import uz.bonvi.call.data.local.CallSessionDao
import uz.bonvi.call.data.local.PendingCallDao
import uz.bonvi.call.data.local.QueuedCallDao
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun database(@ApplicationContext context: Context): BonviCallDatabase =
        Room.databaseBuilder(context, BonviCallDatabase::class.java, BonviCallDatabase.NAME)
            // NO fallbackToDestructiveMigration(). What it would destroy is the
            // upload queue — calls that happened, were recorded, and had not
            // reached the server yet (N8). A migration is written instead.
            .addMigrations(MIGRATION_1_2)
            .build()

    /**
     * 1 → 2: the audio path (2026-09-06).
     *
     * `audio_jobs` is the queue of recordings waiting for their call to be
     * confirmed, and the three columns on `pending_calls` carry the capture
     * outcome from the moment the call ends to the sweep twenty seconds later.
     *
     * Additive only — no table is dropped and no column is rewritten — because
     * every row in this database is a call that happened and has not reached
     * the server yet.
     */
    val MIGRATION_1_2 = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL(
                "CREATE TABLE IF NOT EXISTS audio_jobs (" +
                    "clientCallId TEXT NOT NULL PRIMARY KEY, " +
                    "path TEXT NOT NULL, " +
                    "captureRoute TEXT NOT NULL, " +
                    "recordedAtEpochMillis INTEGER NOT NULL, " +
                    "queuedAtEpochMillis INTEGER NOT NULL, " +
                    "attempts INTEGER NOT NULL DEFAULT 0, " +
                    "lastErrorCode TEXT)",
            )
            db.execSQL("ALTER TABLE pending_calls ADD COLUMN audioPath TEXT")
            db.execSQL("ALTER TABLE pending_calls ADD COLUMN captureRoute TEXT")
            db.execSQL("ALTER TABLE pending_calls ADD COLUMN audioReason TEXT")
        }
    }

    @Provides
    fun queuedCallDao(database: BonviCallDatabase): QueuedCallDao = database.queuedCallDao()

    @Provides
    fun callSessionDao(database: BonviCallDatabase): CallSessionDao = database.callSessionDao()

    @Provides
    fun pendingCallDao(database: BonviCallDatabase): PendingCallDao = database.pendingCallDao()

    @Provides
    fun audioJobDao(database: BonviCallDatabase): AudioJobDao = database.audioJobDao()
}
