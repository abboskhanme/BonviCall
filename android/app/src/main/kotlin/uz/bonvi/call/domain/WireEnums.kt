package uz.bonvi.call.domain

/**
 * The wire vocabulary, as pure Kotlin types (SPEC §7.1: `domain/` holds
 * `CallRecord`, `CaptureRoute`, `Capability`, `Decision`, `PrivacyBoundary`).
 *
 * These are NOT the generated DTOs. `data/remote/dto/` is machine-produced from
 * `contract/openapi-device-v1.json` and is what Moshi serialises; these are what
 * the rest of the app reasons about, and the mapping between them is one file
 * in `data/remote/`. The reason for two sets is that `capture/` must not import
 * a network DTO to say which route produced a file.
 *
 * The `wire` value of every constant below is checked against
 * `contract/openapi-device-v1.json` by `WireEnumContractTest`. A value renamed
 * on the server fails the Android build instead of becoming a runtime 422 on a
 * fleet of 15 phones nobody can force-update.
 */

/** Which mechanism produced the audio. Recorded per call; the M0 baseline and
 *  the panel's device page both depend on this field (SPEC §7.3). */
enum class CaptureRoute(val wire: String) {
    /** The handset's own call recorder. Preferred — S1 showed it is what
     *  captures both voices. */
    OEM_FILE_HARVEST("oem_file_harvest"),

    /** `VOICE_CALL` — the only app-side source that carries BOTH parties.
     *  Refused to an ordinary app from targetSdk 29, so only `legacy28` can
     *  ever report it. Its own value because a fleet whose recordings all came
     *  from `app_mic` is half-deaf and the M0 table has to show which. */
    APP_VOICE_CALL("app_voice_call"),
    APP_VOICE_RECOGNITION("app_voice_recognition"),
    APP_VOICE_COMMUNICATION("app_voice_communication"),
    APP_MIC("app_mic"),
    /** No audio was produced. The call is still uploaded (UC-14). */
    NONE("none"),
}

/**
 * Why a call has no audio. A CLOSED enum, never free text, and `NOT NULL` on
 * the server (N5): "we do not know" is itself a value, and a free-text reason
 * is a gap report nobody can group by.
 */
enum class AudioMissingReason(val wire: String) {
    PENDING_UPLOAD("pending_upload"),
    NOT_EXPECTED("not_expected"),
    RECORDING_ROUTE_UNAVAILABLE("recording_route_unavailable"),
    OEM_RECORDER_OFF("oem_recorder_off"),
    NO_PERMISSION("no_permission"),
    CAPTURE_RETURNED_SILENCE("capture_returned_silence"),
    APP_NOT_RUNNING("app_not_running"),
    UPLOAD_EXPIRED("upload_expired"),
    QUEUE_SPACE_EXHAUSTED("queue_space_exhausted"),
    /** The time-window match found no file that belongs to this call — the
     *  privacy boundary refusing, not a bug (SPEC §7.4). */
    ATTRIBUTION_FAILED("attribution_failed"),
}

enum class CallDirection(val wire: String) {
    INCOMING("incoming"),
    OUTGOING("outgoing"),
}

enum class CallDisposition(val wire: String) {
    ANSWERED("answered"),
    MISSED("missed"),
    REJECTED("rejected"),
    NO_ANSWER("no_answer"),
}

enum class CallSource(val wire: String) {
    /** The service saw the call happen. */
    LIVE_CAPTURE("live_capture"),
    /** The recovery sweep found it afterwards (UC-13). */
    CALL_LOG_RECOVERY("call_log_recovery"),

    /** A cloud telephony provider told the server, not a handset of ours
     *  (T-MZ). The app never sends this — it is here because the enum is the
     *  wire contract and a value the server can emit must be decodable, or a
     *  provider call breaks the "my calls" screen. */
    PROVIDER("provider"),
}

/** Sent on every request and stored on every call and heartbeat, so per-variant
 *  capture rate is a query rather than an experiment someone remembers running. */
enum class AppVariant(val wire: String) {
    LEGACY28("legacy28"),
    MODERN34("modern34"),
}

/**
 * What the panel asked this phone to do (SPEC §4.6, UC-16).
 *
 * The same five kinds arrive on the socket and over REST, and the app answers
 * both the same way — a command delivered by one transport must be
 * indistinguishable from the other in the panel, or a latency measurement means
 * nothing.
 */
enum class CommandKind(val wire: String) {
    /** Click-to-call. The one with a five-second bar. */
    DIAL("dial"),
    CONFIG("config"),
    /** The admin is retiring this installation (UC-08). */
    LOGOUT("logout"),
    /** "Is this phone reachable." Answering IS the whole job. */
    PING("ping"),
    /** Re-run E2's capability checks and report them, so the panel can see what
     *  a phone looks like now rather than what it looked like at enrolment. */
    RECHECK("recheck"),
    ;

    companion object {
        fun fromWire(value: String?): CommandKind? = entries.firstOrNull { it.wire == value }
    }
}

/**
 * Why a command was not carried out.
 *
 * **A refused command is acknowledged, never dropped.** A command with no
 * outcome looks exactly like one that never arrived, and those are two
 * different faults with two different fixes — one is the phone, the other is
 * the channel.
 */
enum class CommandFailure(val wire: String) {
    DEVICE_OFFLINE("device_offline"),
    /** The permission was revoked after enrolment — `CALL_PHONE` is the one
     *  that matters, because without it a dial fails silently. */
    NO_PERMISSION("no_permission"),
    OS_REFUSED("os_refused"),
    ACK_TIMEOUT("ack_timeout"),
    /** Arrived too late to be worth doing (2 minutes, `CommandFreshness`). */
    DISCARDED_STALE("discarded_stale"),
    /** This build does not implement the kind. Honest, and it tells an admin to
     *  stop expecting it rather than leaving the command silent. */
    UNSUPPORTED("unsupported"),
    BUSY("busy"),
}
