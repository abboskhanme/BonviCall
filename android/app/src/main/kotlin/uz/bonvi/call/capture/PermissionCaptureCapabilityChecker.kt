package uz.bonvi.call.capture

import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The capture path's view of this device, until T62 supplies the exercised
 * checks.
 *
 * Both answers are conservative on purpose, and the direction matters:
 *
 *  • **microphone** — reports the RECORD_AUDIO grant. That is weaker than
 *    UC-03 requires: an OEM permission manager can report "granted" while a
 *    test capture returns nothing, which is the `granted_not_working` state.
 *    Over-reporting here costs a `capture_returned_silence` instead of a
 *    `no_permission`, so it is wrong in the cheap direction.
 *
 *  • **oemRecorder** — reports `false`. Wrong in the OTHER direction, so it has
 *    to be argued: claiming the handset's own recorder works when it does not
 *    makes `OemHarvestStrategy` run, find nothing, and report
 *    `attribution_failed` — which says "the privacy boundary refused this
 *    recording" when the truth is "the recorder was switched off". Those are
 *    two different conversations with an employee, and the gap report exists to
 *    have the right one. Until something can actually verify the recorder,
 *    `oem_recorder_off` is the honest answer.
 *
 * TODO(T62): replace with the real capability checkers — one per capability,
 * each EXERCISING the capability rather than reading its flag.
 */
@Singleton
class PermissionCaptureCapabilityChecker @Inject constructor(
    @ApplicationContext private val context: Context,
) : CaptureCapabilityChecker {

    override fun microphoneWorking(): Boolean =
        ContextCompat.checkSelfPermission(context, android.Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    override fun oemRecorderReachable(): Boolean = false
}
