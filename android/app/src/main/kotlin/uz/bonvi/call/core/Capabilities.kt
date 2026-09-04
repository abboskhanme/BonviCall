package uz.bonvi.call.core

import android.os.Build

/**
 * The ONLY file in the app where `Build.VERSION.SDK_INT` may appear.
 *
 * `grep -rn "SDK_INT" android/` outside this file is a violation
 * (CONVENTIONS-CLIENT.md §7, SPEC §7.1), and `ArchitectureRulesTest` fails the
 * build when it happens.
 *
 * The reason is not tidiness. Two product flavours ship — `legacy28` and
 * `modern34` — and a version check scattered through the capture path is how
 * the two silently diverge: one branch gets fixed, the other does not, and the
 * bug only appears on the flavour nobody is running that week. Everything else
 * asks a **capability**, never a version, so behaviour is a question with one
 * answer per device rather than a condition repeated in six places.
 */
object Capabilities {

    /** The running OS level. Exposed as data so callers can REPORT it (the
     *  panel shows OS version per device) without branching on it. */
    val sdkInt: Int = Build.VERSION.SDK_INT

    val manufacturer: String = Build.MANUFACTURER.orEmpty()
    val model: String = Build.MODEL.orEmpty()
    val osRelease: String = Build.VERSION.RELEASE.orEmpty()

    /**
     * Can the OEM recordings folder be reached through raw file paths?
     *
     * True below scoped storage. `OemHarvestStrategy` asks this to choose
     * between the legacy path locator and the MediaStore locator; which one it
     * gets is bound in the flavour's `di/CaptureModule.kt` (SPEC §7.3).
     */
    fun canReadOemRecordingsByPath(): Boolean = sdkInt < Build.VERSION_CODES.Q

    /**
     * Is `MediaRecorder.AudioSource.VOICE_RECOGNITION` usable for capturing the
     * far end?
     *
     * S1 established that this source captures the other party on Samsung and
     * some other handsets, and that the restrictions which close it arrive with
     * the modern target. A `false` here is not "no audio" — it is the
     * `app_mic` route with the near side only, which is still uploaded and
     * still counted (UC-14).
     */
    fun canUseVoiceRecognitionSource(): Boolean = sdkInt < Build.VERSION_CODES.Q

    /** Android 14 requires every foreground service to declare a type. */
    fun requiresForegroundServiceType(): Boolean = sdkInt >= Build.VERSION_CODES.Q

    /**
     * Does the `phoneCall` foreground-service type need the caller to be the
     * default dialer / hold MANAGE_OWN_CALLS / be a device owner?
     *
     * BonviCall is none of the three, so on these devices the `modern34`
     * flavour must start with `microphone|dataSync` alone. M0 measures what
     * that costs (see src/modern34/AndroidManifest.xml).
     */
    fun phoneCallServiceTypeIsRestricted(): Boolean = sdkInt >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE

    /** POST_NOTIFICATIONS became a runtime permission at API 33. */
    fun notificationPermissionRequired(): Boolean = sdkInt >= Build.VERSION_CODES.TIRAMISU

    /** READ_PHONE_NUMBERS split out of READ_PHONE_STATE at API 30 (UC-04). */
    fun phoneNumbersPermissionRequired(): Boolean = sdkInt >= Build.VERSION_CODES.R

    /** All-files access is the only route to the OEM folder under scoped
     *  storage; below Q the legacy read permission is enough. */
    fun requiresAllFilesAccess(): Boolean = sdkInt >= Build.VERSION_CODES.R
}
