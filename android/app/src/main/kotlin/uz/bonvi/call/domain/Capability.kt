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
     * Present because the panel reports on it, NOT because the app asks for it.
     * The contact book is never read and never uploaded (N28), so on every
     * handset this is [CapabilityState.NOT_APPLICABLE]. READ_CONTACTS is
     * absent from both manifests and must stay absent.
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
