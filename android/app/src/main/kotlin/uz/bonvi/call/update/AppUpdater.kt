package uz.bonvi.call.update

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.withContext
import timber.log.Timber
import uz.bonvi.call.BuildConfig
import uz.bonvi.call.data.remote.api.AppUpdateApi
import uz.bonvi.call.data.repository.CallQueueRepository
import uz.bonvi.call.di.IoDispatcher
import uz.bonvi.call.domain.UpdateReadiness
import uz.bonvi.call.service.CallSessionManager
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The in-app updater (T82, N33).
 *
 * Play is not an option, so this is **the** path a fix reaches the fleet by.
 * Three rules, in the order they run:
 *
 * 1. **Never during a call** ([UpdateReadiness]). Installing an APK kills the
 *    process; a restart mid-upload is recoverable and a restart mid-capture is
 *    a lost call. There is no override for this one.
 * 2. **Verify the signature before prompting** ([ApkSignature]). An APK signed
 *    by a different key cannot install as an update — only as an
 *    uninstall-and-reinstall, which destroys the phone's unsent queue. An
 *    agent following the prompt would do exactly that.
 * 3. **Then hand it to the package installer.** The app cannot install
 *    silently and does not pretend to: the OS shows its own confirmation, which
 *    is the same screen the agent saw during enrolment.
 */
@Singleton
class AppUpdater @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: AppUpdateApi,
    private val queue: CallQueueRepository,
    private val sessions: CallSessionManager,
    private val signature: ApkSignature,
    @IoDispatcher private val io: CoroutineDispatcher,
) {

    sealed interface Result {
        /** The OS installer has been opened. The process is about to die. */
        data object InstallerLaunched : Result

        /** Not now, and why. The caller retries on the next heartbeat. */
        data class Deferred(val decision: UpdateReadiness.Decision) : Result

        /** The download or the check failed. Nothing was installed. */
        data class Failed(val reason: String) : Result
    }

    /**
     * @param versionCode the build the server is offering.
     * @param forced true when this build is below the minimum version, so the
     *        queue no longer blocks the update — the phone is being refused
     *        anyway (N34). A call still blocks it.
     */
    suspend fun update(versionCode: Int, forced: Boolean): Result = withContext(io) {
        if (!UpdateReadiness.isNewer(versionCode, BuildConfig.VERSION_CODE)) {
            return@withContext Result.Deferred(UpdateReadiness.Decision.NOT_NEEDED)
        }

        val decision = UpdateReadiness.decide(
            available = true,
            callInProgress = sessions.activeCount() > 0,
            pendingRecords = queue.depth().pending,
            forced = forced,
        )
        if (decision != UpdateReadiness.Decision.INSTALL) {
            Timber.i("Update to %d deferred: %s", versionCode, decision)
            return@withContext Result.Deferred(decision)
        }

        val apk = download(versionCode)
            ?: return@withContext Result.Failed("download_failed")

        when (val verdict = signature.verify(apk)) {
            is ApkSignature.Verdict.Matches -> Unit

            is ApkSignature.Verdict.Mismatch -> {
                // Refuse and DELETE. Leaving it on disk invites somebody to
                // install it by hand, which is the uninstall-and-reinstall that
                // destroys the queue.
                apk.delete()
                Timber.e("Refusing update: signer %s, expected %s", verdict.actual, verdict.expected)
                return@withContext Result.Failed("signature_mismatch")
            }

            is ApkSignature.Verdict.Unverifiable -> {
                apk.delete()
                // Unverifiable is not the same as verified.
                return@withContext Result.Failed("signature_unverifiable")
            }
        }

        // Re-check the call state: the download took time, and a call that
        // started during it is exactly the case this guard exists for.
        if (sessions.activeCount() > 0) {
            return@withContext Result.Deferred(UpdateReadiness.Decision.WAIT_CALL_IN_PROGRESS)
        }

        launchInstaller(apk)
        Result.InstallerLaunched
    }

    private suspend fun download(versionCode: Int): File? {
        val response = @Suppress("TooGenericExceptionCaught") try {
            api.download(versionCode)
        } catch (error: Exception) {
            // Broad, and the specific failure is no network on a phone that is
            // being asked to update. It retries on the next heartbeat.
            Timber.i("Could not download the update")
            return null
        }
        val body = response.body()
        if (!response.isSuccessful || body == null) return null

        val target = File(updateDir(), "bonvicall-$versionCode.apk")
        @Suppress("TooGenericExceptionCaught")
        return try {
            body.byteStream().use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
            target
        } catch (error: Exception) {
            // A full filesystem, most likely on the handset that needed the
            // update most. Partial files are removed rather than left to be
            // "installed" later.
            Timber.w(error, "Could not write the downloaded APK")
            target.delete()
            null
        }
    }

    private fun launchInstaller(apk: File) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", apk)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    /** Cache, not files: a half-finished update is not something to keep, and
     *  the OS may reclaim it if the phone runs out of space. */
    fun updateDir(): File = File(context.cacheDir, "updates").apply { mkdirs() }
}
