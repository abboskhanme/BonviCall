package uz.bonvi.call.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import javax.inject.Qualifier
import javax.inject.Singleton

/**
 * Dispatchers as injected dependencies rather than as `Dispatchers.IO` typed at
 * the call site.
 *
 * The reason is testability, and it is the same reason `Thread {}`,
 * `GlobalScope` and `runBlocking` are forbidden outside tests
 * (CONVENTIONS-CLIENT.md §8): a coroutine whose dispatcher is hard-coded cannot
 * be driven by a test scheduler, so the test either sleeps or is flaky, and a
 * flaky test in the upload path is a test that gets deleted.
 */
@Qualifier @Retention(AnnotationRetention.BINARY) annotation class IoDispatcher

@Qualifier @Retention(AnnotationRetention.BINARY) annotation class DefaultDispatcher

@Qualifier @Retention(AnnotationRetention.BINARY) annotation class MainDispatcher

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides @IoDispatcher fun ioDispatcher(): CoroutineDispatcher = Dispatchers.IO

    @Provides @DefaultDispatcher fun defaultDispatcher(): CoroutineDispatcher = Dispatchers.Default

    @Provides @MainDispatcher fun mainDispatcher(): CoroutineDispatcher = Dispatchers.Main

    /** `BuildConfig.APP_VARIANT`, injected rather than read, so anything that
     *  reports it (every request, every heartbeat, every call) can be tested
     *  for both flavours without building both. */
    @Provides @Singleton @AppVariantName
    fun appVariant(): String = uz.bonvi.call.BuildConfig.APP_VARIANT
}

@Qualifier @Retention(AnnotationRetention.BINARY) annotation class AppVariantName
