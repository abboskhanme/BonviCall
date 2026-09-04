package uz.bonvi.call.di

import android.content.Context
import androidx.room.Room
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import uz.bonvi.call.data.local.BonviCallDatabase
import uz.bonvi.call.data.local.CallSessionDao
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
            .build()

    @Provides
    fun queuedCallDao(database: BonviCallDatabase): QueuedCallDao = database.queuedCallDao()

    @Provides
    fun callSessionDao(database: BonviCallDatabase): CallSessionDao = database.callSessionDao()
}
