package uz.bonvi.call.domain

/**
 * The twelve capabilities of SPEC §3.1, and their six states.
 *
 * The point of the enum is UC-03's finding: a granted permission is not a
 * working capability. An OEM permission manager can report "granted" while the
 * call log query returns nothing, so every check must EXERCISE the capability
 * — a one-second test capture, a one-row query — and
 * [CapabilityState.GRANTED_NOT_WORKING] is a reportable state rather than an
 * impossible one. T62 implements one checker per capability against this list.
 */
enum class Capability(val wire: String) {
    PHONE_STATE("phone_state"),
    CALL_LOG("call_log"),
    MICROPHONE("microphone"),

    /**
     * **Optional**, and it degrades one field only (SPEC §7.8).
     *
     * With it, a call the app captured on the registered number can carry the
     * name of the person spoken to. Without it the call ships without a name,
     * which is not a failure and never becomes an `audio_missing_reason` —
     * E2 marks the step *ixtiyoriy* and an agent may skip it.
     *
     * N28 allows a resolved NAME off the handset; it does not allow the book.
     * `capture/ContactNameResolver.kt` is the only reader, it looks up one
     * number at a time, and it caches nothing.
     */
    CONTACTS("contacts"),

    NOTIFICATIONS("notifications"),

    /** UC-16 click-to-call. On T104's keep-list: without CALL_PHONE the dial
     *  command fails silently. */
    CALL_PHONE("call_phone"),

    BATTERY_EXEMPTION("battery_exemption"),
    STORAGE_ACCESS("storage_access"),

    /** The OEM's own autostart / protected-app list. Not a permission at all on
     *  most devices — a settings screen per manufacturer (E3, SPEC §8.2). */
    OEM_AUTOSTART("oem_autostart"),

    FOREGROUND_SERVICE("foreground_service"),

    /** Whether the handset's own call recorder is on. Not grantable by us: the
     *  user turns it on in the dialer, and E3 explains how per OEM. */
    OEM_RECORDER("oem_recorder"),

    /** Guard 1 of the privacy boundary: can the OS tell us which SIM a call was
     *  on? If not, nothing is captured (SPEC §7.4). */
    SUBSCRIPTION_RESOLUTION("subscription_resolution"),
}

/**
 * The runtime permission behind a capability, or null when it is a settings
 * screen rather than a dialog.
 *
 * Null is not "no permission needed" — battery exemption and all-files access
 * are granted on a settings page, and asking for them with
 * `RequestPermission()` silently does nothing, which looks to the agent like a
 * button that is broken.
 */
fun Capability.runtimePermission(): String? = when (this) {
    Capability.PHONE_STATE -> android.Manifest.permission.READ_PHONE_STATE
    Capability.CALL_LOG -> android.Manifest.permission.READ_CALL_LOG
    Capability.MICROPHONE -> android.Manifest.permission.RECORD_AUDIO
    Capability.CALL_PHONE -> android.Manifest.permission.CALL_PHONE
    Capability.NOTIFICATIONS -> "android.permission.POST_NOTIFICATIONS"
    // Optional, and the only permission in E2 an agent may decline without
    // blocking E6 (SPEC §8.2 marks it *ixtiyoriy*).
    Capability.CONTACTS -> android.Manifest.permission.READ_CONTACTS
    Capability.BATTERY_EXEMPTION, Capability.STORAGE_ACCESS, Capability.OEM_AUTOSTART,
    Capability.FOREGROUND_SERVICE, Capability.OEM_RECORDER, Capability.SUBSCRIPTION_RESOLUTION,
    -> null
}

enum class CapabilityState(val wire: String) {
    GRANTED_WORKING("granted_working"),

    /** The permission says yes and the capability does not work. UC-03 names
     *  this case explicitly; it is the OEM permission-manager trap and the
     *  single most common reason an enrolment looks finished and is not. */
    GRANTED_NOT_WORKING("granted_not_working"),

    DENIED("denied"),
    DENIED_PERMANENTLY("denied_permanently"),
    NOT_APPLICABLE("not_applicable"),
    UNKNOWN("unknown"),
}
