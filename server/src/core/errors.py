"""Errors — one hierarchy, one envelope (CONVENTIONS.md §9, N35, SPEC §4.0).

Routers raise :class:`AppError` subclasses. ``HTTPException`` is forbidden:
FastAPI renders it as ``{"detail": ...}``, which is not the envelope the
Android client parses, and a response the client cannot parse is
indistinguishable from a corrupted body — its upload queue then cannot decide
whether to retry.

``code`` is machine contract. It is snake_case, it is stable forever, its
meaning never changes, and it is listed here so that ``contract/`` can carry
the whole set. ``message`` is what a human reads and lives only in
``core/messages_uz.py``.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """Every error code the server can emit.

    The values come from SPEC §4 (the API contract) and CONVENTIONS.md §9.
    Where the two documents named the same failure differently the SPEC wins,
    because an error code is wire behaviour and SPEC §0 says behaviour is its
    call; the four cases are recorded in ``docs/ASSUMPTIONS.md``.
    """

    # --- Generic ---------------------------------------------------------
    APP_ERROR = "app_error"
    BAD_REQUEST = "bad_request"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    RATE_LIMITED = "rate_limited"

    # --- Auth and access (SPEC §4.1, §4.2) --------------------------------
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    INSTALLATION_MISMATCH = "installation_mismatch"
    INSTALLATION_REVOKED = "installation_revoked"
    REFRESH_REUSED = "refresh_reused"
    VERIFICATION_REQUIRED = "verification_required"
    HEADER_MISSING = "header_missing"
    APP_VERSION_UNSUPPORTED = "app_version_unsupported"

    # --- Users and roles (SPEC §4.7) --------------------------------------
    SALES_USER_REQUIRES_AGENT = "sales_user_requires_agent"
    CANNOT_MODIFY_SELF = "cannot_modify_self"
    LAST_ADMIN = "last_admin"

    # --- Identity: numbers, agents, assignments (SPEC §3.3, §4.7) ---------
    NUMBER_ALREADY_ASSIGNED = "number_already_assigned"
    ASSIGNMENT_OVERLAP = "assignment_overlap"
    AGENT_HAS_OPEN_ASSIGNMENT = "agent_has_open_assignment"

    # --- Enrolment (SPEC §4.2, §9) ----------------------------------------
    ENROLMENT_CODE_NOT_FOUND = "enrolment_code_not_found"
    ENROLMENT_CODE_USED = "enrolment_code_used"
    ENROLMENT_CODE_EXPIRED = "enrolment_code_expired"
    ENROLMENT_CODE_REVOKED = "enrolment_code_revoked"
    INSTALLATION_ALREADY_ACTIVE = "installation_already_active"
    MSISDN_UNAVAILABLE = "msisdn_unavailable"
    NUMBER_MISMATCH = "number_mismatch"
    CALLBACK_RECEIVER_DOWN = "callback_receiver_down"

    # --- Calls (SPEC §3.10, §4.4) -----------------------------------------
    CALL_NOT_FOUND = "call_not_found"
    CALL_IDENTITY_CONFLICT = "call_identity_conflict"
    DELETE_NOT_ALLOWED = "delete_not_allowed"

    # --- Audio (SPEC §4.5, §4.8) ------------------------------------------
    AUDIO_NOT_ATTRIBUTABLE = "audio_not_attributable"
    AUDIO_EXPIRED = "audio_expired"
    AUDIO_NOT_FOUND = "audio_not_found"
    UPLOAD_EXPIRED = "upload_expired"
    CHUNK_OFFSET_MISMATCH = "chunk_offset_mismatch"
    CHUNK_CHECKSUM_MISMATCH = "chunk_checksum_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    RANGE_NOT_SATISFIABLE = "range_not_satisfiable"

    # --- Settings (SPEC §3.11) --------------------------------------------
    RETENTION_CONFIRMATION_REQUIRED = "retention_confirmation_required"

    # --- App versions (N33, N34) ------------------------------------------
    #: Raising the minimum supported version strands every handset below it,
    #: and these are personally owned phones: a stranded one stops reporting
    #: until somebody physically reaches that salesperson. The caller has to
    #: state the current count, so the change is a decision and not a typo.
    STRANDED_COUNT_MISMATCH = "stranded_count_mismatch"
    #: The uploaded file is not an APK, or is signed by a key that is not ours.
    APK_REJECTED = "apk_rejected"

    @classmethod
    def all_codes(cls) -> frozenset[str]:
        """Every declared code. Used by the contract export and by tests."""
        return frozenset(
            value
            for name, value in vars(cls).items()
            if name.isupper() and isinstance(value, str)
        )


class AppError(Exception):
    """Base class. Knows nothing about FastAPI — ``main.py`` renders it.

    :param message: overrides the Uzbek catalogue entry. Pass one only for a
        failure whose text cannot be known in advance; the catalogue is where
        user-facing wording belongs (§14).
    :param detail: optional, machine-readable, part of the envelope (SPEC §4.0).
        Never put a token, a password or an enrolment code in it (N26).
    """

    status_code: int = 400
    code: str = ErrorCode.APP_ERROR

    def __init__(
        self,
        code: str | None = None,
        *,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.detail = detail
        self.message = message
        super().__init__(self.code)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code!r}, status={self.status_code})"


class BadRequestError(AppError):
    """400 — the request is malformed in a way Pydantic did not catch."""

    status_code = 400
    code = ErrorCode.BAD_REQUEST


class UnauthorizedError(AppError):
    """401 — no token, an expired token, or a token bound elsewhere (N24)."""

    status_code = 401
    code = ErrorCode.UNAUTHORIZED


class ForbiddenError(AppError):
    """403 — authenticated, but the role does not carry the permission.

    Never used for "this row belongs to another agent" — that is 404
    (SPEC §4.1 rule 2), because 403 confirms the row exists.
    """

    status_code = 403
    code = ErrorCode.FORBIDDEN


class NotFoundError(AppError):
    """404 — absent, **or** present and owned by somebody else."""

    status_code = 404
    code = ErrorCode.NOT_FOUND


class MethodNotAllowedError(AppError):
    """405 — the operation does not exist for anybody.

    Its only use in release 1 is ``DELETE`` on a call or its audio, for every
    role including ``admin`` (UC-26). Not in CONVENTIONS.md §9's subclass list;
    SPEC §4.0's status table requires it.
    """

    status_code = 405
    code = ErrorCode.DELETE_NOT_ALLOWED


class ConflictError(AppError):
    """409 — the request is well formed but the world disagrees."""

    status_code = 409
    code = ErrorCode.CONFLICT


class GoneError(AppError):
    """410 — it existed and is deliberately no longer here.

    An expired recording is a 410, never a 500 and never an empty 200
    (UC-26 acceptance criterion).
    """

    status_code = 410
    code = ErrorCode.AUDIO_EXPIRED


class PayloadTooLargeError(AppError):
    """413 — over the limits in SPEC §4.0."""

    status_code = 413
    code = ErrorCode.PAYLOAD_TOO_LARGE


class RangeNotSatisfiableError(AppError):
    """416 — an audio ``Range`` outside the file (SPEC §4.8)."""

    status_code = 416
    code = ErrorCode.RANGE_NOT_SATISFIABLE


class ValidationError(AppError):
    """422 — cross-field or cross-row validation done in a service.

    Field-shape validation is Pydantic's job and arrives through the
    ``RequestValidationError`` handler with the same code.
    """

    status_code = 422
    code = ErrorCode.VALIDATION_ERROR


class VersionUnsupportedError(AppError):
    """426 — the app is below the minimum version (N34).

    Only ever raised after the device's queue has drained; refusing an old
    client must never destroy data (SPEC §4.3).
    """

    status_code = 426
    code = ErrorCode.APP_VERSION_UNSUPPORTED


class RateLimitedError(AppError):
    """429 — over the per-principal limit in SPEC §4.0.

    Carries ``retry_after_sec`` so the handler can set ``Retry-After``.
    """

    status_code = 429
    code = ErrorCode.RATE_LIMITED

    def __init__(
        self,
        code: str | None = None,
        *,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
        retry_after_sec: int = 60,
    ) -> None:
        super().__init__(code, message=message, detail=detail)
        self.retry_after_sec = retry_after_sec


__all__ = [
    "AppError",
    "BadRequestError",
    "ConflictError",
    "ErrorCode",
    "ForbiddenError",
    "GoneError",
    "MethodNotAllowedError",
    "NotFoundError",
    "PayloadTooLargeError",
    "RangeNotSatisfiableError",
    "RateLimitedError",
    "UnauthorizedError",
    "ValidationError",
    "VersionUnsupportedError",
]
