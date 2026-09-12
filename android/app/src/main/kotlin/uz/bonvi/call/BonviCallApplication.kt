package uz.bonvi.call

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import timber.log.Timber
import uz.bonvi.call.core.FileLogTree
import uz.bonvi.call.core.RedactingTree
import javax.inject.Inject

/**
 * The application. Two jobs, both of which every later task depends on.
 *
 * 1. **Hilt's root.** `@HiltAndroidApp` generates the component the service,
 *    the receivers, the workers and the ViewModels are injected from.
 * 2. **WorkManager with an injected factory.** The default initialiser is
 *    removed in the manifest so this one runs instead; without that, a
 *    `@HiltWorker` has no dependencies and fails at runtime, on the upload
 *    path, on a phone.
 *
 * Every Timber log goes through [RedactingTree]: a token, a password or an
 * enrolment code in a log line is an N26 finding, and these are the employees'
 * own phones whose log buffers end up in support chats.
 */
@HiltAndroidApp
class BonviCallApplication : Application(), Configuration.Provider {

    @Inject lateinit var workerFactory: HiltWorkerFactory

    override fun onCreate() {
        super.onCreate()
        Timber.plant(RedactingTree())
        if (BuildConfig.DEBUG) {
            // A debug build keeps its own copy of the log where `run-as` can
            // read it, because a handset in the field has no logcat reader
            // attached. Never in a release build -- see FileLogTree.
            Timber.plant(FileLogTree(java.io.File(filesDir, FileLogTree.RELATIVE_PATH)))
        }
        Timber.i("BonviCall %s (%s) starting", BuildConfig.VERSION_NAME, BuildConfig.APP_VARIANT)
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()
}
