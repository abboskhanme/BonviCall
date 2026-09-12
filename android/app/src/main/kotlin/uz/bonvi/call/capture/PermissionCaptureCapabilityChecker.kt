package uz.bonvi.call.capture

import android.content.Context
import android.content.pm.PackageManager
import android.os.Environment
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import timber.log.Timber
import uz.bonvi.call.enrolment.StorageAccessProbe
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The capture path's view of this device.
 *
 * The direction of each answer's error matters:
 *
 *  • **microphone** — reports the RECORD_AUDIO grant. That is weaker than
 *    UC-03 requires: an OEM permission manager can report "granted" while a
 *    test capture returns nothing, which is the `granted_not_working` state.
 *    Over-reporting here costs a `capture_returned_silence` instead of a
 *    `no_permission`, so it is wrong in the cheap direction.
 *
 *  • **oemRecorder** — was a hard-coded `false`, and that single line disabled
 *    the PREFERRED capture route on every handset in the fleet. With it off,
 *    `OemHarvestStrategy.isSupported()` returned false, the strategy never ran,
 *    and every call fell to the app's own microphone — near side only, on a
 *    product whose entire purpose is hearing the customer. Measured on
 *    Ilyoshon's Xiaomi 13 Lite (2026-09-12): the handset had written a clean
 *    both-voices file for every call and this stub threw the route away.
 *
 *    It is a real probe now, and it EXERCISES the capability the way the rest
 *    of this flow demands: the folder must be reachable (flavour-aware, via
 *    [StorageAccessProbe]) AND actually hold a recording. Requiring a file is
 *    what keeps the honest label — an empty-but-reachable folder is a recorder
 *    that is switched off (`oem_recorder_off`), not a boundary refusal
 *    (`attribution_failed`).
 */
@Singleton
class PermissionCaptureCapabilityChecker @Inject constructor(
    @ApplicationContext private val context: Context,
    /** Flavour-aware "can this build reach the OEM recordings folder?" — the
     *  same probe the `storage_access` capability reports. */
    private val storageProbe: StorageAccessProbe,
) : CaptureCapabilityChecker {

    override fun microphoneWorking(): Boolean =
        ContextCompat.checkSelfPermission(context, android.Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    /**
     * Reachable AND recording. Both halves matter:
     *  - [StorageAccessProbe] answers reachability without a flavour branch.
     *  - a real file in one of [OemRecordingFolders.CANDIDATES] proves the
     *    recorder is actually on, which is what separates `oem_recorder_off`
     *    from `attribution_failed` in the gap report.
     *
     * Read-only: it lists folders and reads file sizes, and never opens, moves
     * or modifies anything (CONVENTIONS.md §8.3).
     */
    override fun oemRecorderReachable(): Boolean = storageProbe.hasAccess() && hasAnyRecording()

    private fun hasAnyRecording(): Boolean =
        @Suppress("TooGenericExceptionCaught")
        try {
            @Suppress("DEPRECATION")
            val root = Environment.getExternalStorageDirectory()
            OemRecordingFolders.CANDIDATES.any { relative ->
                File(root, relative).let { dir ->
                    dir.isDirectory && dir.canRead() &&
                        dir.listFiles()?.any {
                            it.isFile && it.length() >= OemRecordingLocator.MIN_FILE_BYTES
                        } == true
                }
            }
        } catch (error: Exception) {
            // A permission revoked mid-flight or an OEM that refuses the listing
            // is "we cannot tell", which is not "reachable".
            Timber.w(error, "Could not probe the OEM recordings folders")
            false
        }
}
