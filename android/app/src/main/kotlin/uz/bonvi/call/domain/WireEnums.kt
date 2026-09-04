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
}

/** Sent on every request and stored on every call and heartbeat, so per-variant
 *  capture rate is a query rather than an experiment someone remembers running. */
enum class AppVariant(val wire: String) {
    LEGACY28("legacy28"),
    MODERN34("modern34"),
}
