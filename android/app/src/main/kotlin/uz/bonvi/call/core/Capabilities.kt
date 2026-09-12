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

    // Four predicates were removed here, all of them with no caller:
    // `requiresForegroundServiceType`, `notificationPermissionRequired` and
    // `phoneNumbersPermissionRequired` — the manifest and the permission
    // checks answer those questions directly — and
    // `phoneCallServiceTypeIsRestricted`, whose documentation had also become
    // wrong: it said the app is not the default dialer, does not hold
    // MANAGE_OWN_CALLS and is not a device owner, and the app has held
    // MANAGE_OWN_CALLS since 2026-09-06. An uncalled predicate carrying a
    // stale claim is worse than no predicate: the next person reads it as
    // current.



    /**
     * Can `MediaMuxer` write Opus into an Ogg container?
     *
     * `MUXER_OUTPUT_OGG` arrived at API 29, and the `legacy28` variant has to
     * run on API 26–28 — which is the variant S1 says captures both voices, so
     * it cannot simply be dropped. Below this the decided fallback is AAC-LC in
     * MP4 at the same 24 kbps mono 16 kHz (SPEC §7.6), so the storage and data
     * budgets are identical either way.
     */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.Q)
    fun canMuxOpusOgg(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q

    /** `TelephonyCallback` replaced `PhoneStateListener` at API 31. Below it
     *  the deprecated listener is the only option, which is a capability
     *  question rather than a preference. */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.S)
    fun supportsTelephonyCallback(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S

    /** `PackageInfo.signingInfo` replaced the deprecated `signatures` array at
     *  API 28. Below it the old field is the only way to read a signer, and
     *  refusing to check would be worse than checking with a deprecated API. */
    @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.P)
    fun supportsSigningInfo(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P



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
