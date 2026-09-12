package uz.bonvi.call.core

/**
 * The error envelope, device side (CONVENTIONS.md §9, SPEC §4.0, N35).
 *
 * Every non-2xx response the server produces — including 500 — is
 * `{"error": {"code": "...", "message": "...", ...}}`. The upload queue
 * branches on `code` and never on `message`, and a response that does not match
 * the envelope is indistinguishable from a corrupted body, at which point the
 * queue cannot decide whether to retry. That is why the server has a generic
 * 500 handler at all.
 *
 * The values below are the same catalogue as `contract/error-codes.json`;
 * `ErrorCodeContractTest` fails when the two drift.
 */
enum class ErrorCode(val wire: String) {
    // Generic
    APP_ERROR("app_error"),
    BAD_REQUEST("bad_request"),
    VALIDATION_ERROR("validation_error"),
    INTERNAL_ERROR("internal_error"),
    NOT_FOUND("not_found"),
    METHOD_NOT_ALLOWED("method_not_allowed"),
    CONFLICT("conflict"),
    PAYLOAD_TOO_LARGE("payload_too_large"),
    RATE_LIMITED("rate_limited"),

    // Auth and access
    UNAUTHORIZED("unauthorized"),
    FORBIDDEN("forbidden"),
    INSTALLATION_MISMATCH("installation_mismatch"),
    INSTALLATION_REVOKED("installation_revoked"),
    REFRESH_REUSED("refresh_reused"),
    VERIFICATION_REQUIRED("verification_required"),
    HEADER_MISSING("header_missing"),
    APP_VERSION_UNSUPPORTED("app_version_unsupported"),

    // Users and roles (panel-only, present so the catalogue is complete)
    SALES_USER_REQUIRES_AGENT("sales_user_requires_agent"),
    CANNOT_MODIFY_SELF("cannot_modify_self"),
    LAST_ADMIN("last_admin"),

    // Identity
    NUMBER_ALREADY_ASSIGNED("number_already_assigned"),
    ASSIGNMENT_OVERLAP("assignment_overlap"),
    AGENT_HAS_OPEN_ASSIGNMENT("agent_has_open_assignment"),

    // Enrolment
    ENROLMENT_CODE_NOT_FOUND("enrolment_code_not_found"),
    ENROLMENT_CODE_USED("enrolment_code_used"),
    ENROLMENT_CODE_EXPIRED("enrolment_code_expired"),
    ENROLMENT_CODE_REVOKED("enrolment_code_revoked"),
    INSTALLATION_ALREADY_ACTIVE("installation_already_active"),
    MSISDN_UNAVAILABLE("msisdn_unavailable"),
    NUMBER_MISMATCH("number_mismatch"),
    CALLBACK_RECEIVER_DOWN("callback_receiver_down"),

    /** Route 3 is off on this server, so an admin attesting from the panel is
     *  the only way this handset finishes. E5 says so and polls for it rather
     *  than offering a button that cannot work. */
    SELF_DECLARED_DISABLED("self_declared_disabled"),

    // Calls
    CALL_NOT_FOUND("call_not_found"),
    CALL_IDENTITY_CONFLICT("call_identity_conflict"),
    DELETE_NOT_ALLOWED("delete_not_allowed"),

    // Audio
    AUDIO_NOT_ATTRIBUTABLE("audio_not_attributable"),
    AUDIO_EXPIRED("audio_expired"),
    AUDIO_NOT_FOUND("audio_not_found"),
    UPLOAD_EXPIRED("upload_expired"),
    CHUNK_OFFSET_MISMATCH("chunk_offset_mismatch"),
    CHUNK_CHECKSUM_MISMATCH("chunk_checksum_mismatch"),
    CHECKSUM_MISMATCH("checksum_mismatch"),
    RANGE_NOT_SATISFIABLE("range_not_satisfiable"),

    // Settings
    RETENTION_CONFIRMATION_REQUIRED("retention_confirmation_required"),

    // App releases (T81, T82)
    /** An uploaded APK is signed by the wrong key. The server checks the signer
     *  server-side; `ApkSignature` checks it again on the phone before
     *  installing, because the consequence there is an uninstall-and-reinstall
     *  that destroys the queue (docs/APK-SIGNING.md). */
    APK_REJECTED("apk_rejected"),

    /** The stranded-record count the device reported disagrees with what the
     *  server holds. A reconciliation fault, not a transport one. */
    STRANDED_COUNT_MISMATCH("stranded_count_mismatch"),
    ;

    companion object {
        private val BY_WIRE: Map<String, ErrorCode> = entries.associateBy { it.wire }

        /** Null for a code this build does not know — a newer server can add
         *  one, and an unknown code must not crash a fleet we cannot update. */
        fun fromWire(wire: String): ErrorCode? = BY_WIRE[wire]
    }
}

/**
 * A failure that reached us with the envelope intact.
 *
 * [code] is kept as the raw string as well as the parsed [errorCode], so a code
 * introduced after this APK shipped is still logged and reported rather than
 * swallowed.
 */
data class ApiFailure(
    val status: Int,
    val code: String,
    val message: String?,
    val requestId: String? = null,
) {
    val errorCode: ErrorCode? get() = ErrorCode.fromWire(code)

    /**
     * Retrying a 4xx replays a request the server has already judged. The two
     * exceptions are 401 (refresh, then retry once) and 429 (the server said
     * when). 426 is never retried and never destroys the queue — the client
     * drains first and is refused afterwards (SPEC §4.3).
     */
    val isRetryable: Boolean
        get() = when {
            status >= 500 -> true
            status == 429 -> true
            status == 408 -> true
            else -> false
        }
}

/** Anything that failed before a response existed. */
sealed interface TransportFailure {
    /** No network, DNS failure, connection reset. Retry later, keep the row. */
    data class Offline(val cause: Throwable) : TransportFailure

    /**
     * TLS failed. **Never bypassed** (N22, CONVENTIONS-CLIENT.md §9): a
     * certificate error on an employee's own handset is exactly the case where
     * bypassing it would hand every recorded conversation to whoever installed
     * the root.
     */
    data class Tls(val cause: Throwable) : TransportFailure

    /** The body was not the envelope. Not retryable as data; reported. */
    data class MalformedResponse(val status: Int) : TransportFailure
}
