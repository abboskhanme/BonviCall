package uz.bonvi.call.core

import android.os.Build
import androidx.annotation.ChecksSdkIntAtLeast

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
     * A stable hash of `Build.FINGERPRINT`.
     *
     * The raw fingerprint names the exact firmware build on somebody's personal
     * handset, and the server has no use for that (N28) — what it needs is
     * "is this the same phone as last time", which a hash answers. Stable
     * across reinstalls on the same device, which is what makes a re-enrolment
     * recognisable as the same handset rather than a new one.
     */
    fun buildFingerprintHash(): String {
        val raw = Build.FINGERPRINT.orEmpty()
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(raw.toByteArray())
        return digest.joinToString("") { "%02x".format(it) }
    }

    /**
     * Can the OEM recordings folder be reached through raw file paths?
     *
     * True below scoped storage. `OemHarvestStrategy` asks this to choose
     * between the legacy path locator and the MediaStore locator; which one it
     * gets is bound in the flavour's `di/CaptureModule.kt` (SPEC §7.3).
     */
    fun canReadOemRecordingsByPath(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q

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
    fun canUseVoiceRecognitionSource(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q

    /** Android 14 requires every foreground service to declare a type. */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.Q)
    fun requiresForegroundServiceType(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

    /**
     * Does the `phoneCall` foreground-service type need the caller to be the
     * default dialer / hold MANAGE_OWN_CALLS / be a device owner?
     *
     * BonviCall is none of the three, so on these devices the `modern34`
     * flavour must start with `microphone|dataSync` alone. M0 measures what
     * that costs (see src/modern34/AndroidManifest.xml).
     */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
    fun phoneCallServiceTypeIsRestricted(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE

    /** POST_NOTIFICATIONS became a runtime permission at API 33. */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.TIRAMISU)
    fun notificationPermissionRequired(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU

    /** READ_PHONE_NUMBERS split out of READ_PHONE_STATE at API 30 (UC-04). */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.R)
    fun phoneNumbersPermissionRequired(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.R

    /**
     * All-files access is the only route to the OEM folder under scoped
     * storage; below Q the legacy read permission is enough.
     *
     * `@ChecksSdkIntAtLeast` is what keeps the "ask a capability, never a
     * version" rule (CONVENTIONS-CLIENT.md §7) compatible with lint's `NewApi`
     * check: it tells lint that this function IS a version guard, so a caller
     * can write `if (Capabilities.requiresAllFilesAccess())` around an API 30
     * call and stay both readable and safe. Without it the only options are a
     * raw `SDK_INT` at the call site — which the architecture test forbids —
     * or a blanket `@SuppressLint`, which forbids nothing.
     */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.R)
    fun requiresAllFilesAccess(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
}
