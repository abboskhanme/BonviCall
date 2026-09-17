"""Every PostgreSQL native enum in the product, in one place (SPEC §3.1).

They live in ``core/`` rather than in a module because they are wire
vocabulary: the same ``capture_route`` value is written by the Android client,
stored by the ``calls`` module, read by the ``audio`` module and exported to
BonviZvonki. Putting them in one module's ``models.py`` would make every other
module import that module's models, which CONVENTIONS.md §2 forbids.

Two rules that are not optional:

* Bind them with :func:`pg_enum`, never with a bare ``SAEnum(...)``. Without
  ``values_callable`` SQLAlchemy stores the *member name* — upper case — and
  the data becomes unreadable (the BonviZvonki idiom, SPEC §3.0).
* They are **closed**. ``audio_missing_reason`` in particular is ``NOT NULL``
  on every audio-less call and never free text (N5), which is what makes
  "100 % of calls carry a reason" checkable rather than aspirational.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Bind a ``StrEnum`` to a PostgreSQL native enum type by its **values**."""
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        native_enum=True,
    )


class UserRole(StrEnum):
    """A panel login's role (SPEC §3.2).

    ``service`` is deliberately absent: machine access is a ``service_tokens``
    row, because a machine has no password, no session and no navigation. The
    authorisation registry in ``core/permissions.py`` covers both and a test
    asserts these three are a subset of it.

    ``viewer`` was removed on 2026-09-05 with the TV board — see
    ``core.permissions.Role``.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    SALES = "sales"


class CallDirection(StrEnum):
    """Ours, not BonviZvonki's ``inbound``/``outbound``.

    The export (SPEC §4.9) maps ours onto theirs in exactly one place, so the
    two vocabularies never leak into each other.
    """

    INCOMING = "incoming"
    OUTGOING = "outgoing"


class CallDisposition(StrEnum):
    """UC-11's five classes are direction x disposition.

    ``missed`` and ``rejected`` are incoming-only, ``no_answer`` is
    outgoing-only — enforced by a CHECK, so the invalid combinations are
    unrepresentable rather than merely unused.
    """

    ANSWERED = "answered"
    MISSED = "missed"
    REJECTED = "rejected"
    NO_ANSWER = "no_answer"


class CallType(StrEnum):
    """Internal vs external (UC-25). ``unknown`` is the mandatory default.

    An empty line directory yields ``unknown``, never ``external``:
    BonviZvonki defaulted to external and 82 of 98 calls were mislabelled.
    """

    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class CallSource(StrEnum):
    """How the record reached us."""

    LIVE_CAPTURE = "live_capture"
    CALL_LOG_RECOVERY = "call_log_recovery"

    #: A cloud telephony provider told us, rather than a handset of ours
    #: (T-MZ). Its own value because everything downstream reads differently
    #: for it: there is no installation health behind the row, no capability
    #: history, and "the app was not running" can never be the reason its audio
    #: is missing. The gap report has to be able to tell the two populations
    #: apart or its percentages mix a fleet we control with one we do not.
    PROVIDER = "provider"


class AudioMissingReason(StrEnum):
    """Why a call has no audio. Closed, ``NOT NULL`` whenever audio is absent (N5).

    UC-14 names six; SPEC §3.9 justifies the other four one by one. The gap
    report's denominator excludes ``pending_upload`` and ``not_expected``,
    which is what keeps "% of answered calls with audio" honest.
    """

    PENDING_UPLOAD = "pending_upload"
    NOT_EXPECTED = "not_expected"
    RECORDING_ROUTE_UNAVAILABLE = "recording_route_unavailable"
    OEM_RECORDER_OFF = "oem_recorder_off"
    NO_PERMISSION = "no_permission"
    CAPTURE_RETURNED_SILENCE = "capture_returned_silence"
    APP_NOT_RUNNING = "app_not_running"
    UPLOAD_EXPIRED = "upload_expired"
    QUEUE_SPACE_EXHAUSTED = "queue_space_exhausted"
    ATTRIBUTION_FAILED = "attribution_failed"


class DeviceAudioState(StrEnum):
    """What the employee's own-calls screen says about one call's recording.

    A **derived** value, not a column: ``has_audio`` and ``audio_missing_reason``
    together answer it, and the app needs one non-null thing to switch on.

    It is deliberately not a value added to :class:`AudioMissingReason`. Every
    member of that enum means audio is *absent* — its own docstring says
    "NOT NULL whenever audio is absent" — so a ``recorded`` member would make
    the name a lie and would arrive as an unparseable value in every client
    already generated against it.
    """

    RECORDED = "recorded"
    """The server holds the recording and it can be played."""

    EXPIRED = "expired"
    """It existed and retention removed it (UC-26). Not the same as never having one."""

    QUEUED = "queued"
    """On the phone, not yet uploaded. Not a failure — audio in flight."""

    NOT_EXPECTED = "not_expected"
    """An unanswered call had no conversation to record (UC-14)."""

    MISSING = "missing"
    """Expected and not captured. ``audio_missing_reason`` says why."""


class CaptureRoute(StrEnum):
    """Which mechanism produced the recording (S1, the M0 baseline).

    ``NONE`` may only appear with ``has_audio = false``.
    """

    OEM_FILE_HARVEST = "oem_file_harvest"

    #: `MediaRecorder.AudioSource.VOICE_CALL` — the only app-side source that
    #: carries BOTH parties. Android refuses it to an ordinary app from
    #: targetSdk 29, which is why the `legacy28` flavour exists and why this
    #: value will only ever be reported by it. Ranked above the rest: a fleet
    #: whose recordings all came from `app_mic` is half-deaf, and the M0 table
    #: has to be able to say which handsets got the far end.
    APP_VOICE_CALL = "app_voice_call"
    APP_VOICE_RECOGNITION = "app_voice_recognition"
    APP_VOICE_COMMUNICATION = "app_voice_communication"
    APP_MIC = "app_mic"
    NONE = "none"


class AudioCodec(StrEnum):
    """Opus is the target; AAC-LC is the decided fallback and is counted (§7.6)."""

    OPUS = "opus"
    AAC_LC = "aac_lc"


class AudioContainer(StrEnum):
    """Pairs with the codec: Opus in Ogg, AAC-LC in MP4."""

    OGG = "ogg"
    MP4 = "mp4"


class AppVariant(StrEnum):
    """The ``targetSdk`` product flavour (D-06).

    Reported on every heartbeat, stored on every call, so capture rate is
    measurable per variant and not only per handset model.
    """

    LEGACY28 = "legacy28"
    MODERN34 = "modern34"


class InstallationStatus(StrEnum):
    """Lifecycle of one app installation bound to one registered number."""

    PENDING = "pending"
    ACTIVE = "active"
    REPLACED = "replaced"
    REVOKED = "revoked"
    REVOKED_PENDING_CONFIRMATION = "revoked_pending_confirmation"


class VerificationMethod(StrEnum):
    """How we proved the phone holds the registered number (UC-04, T142).

    Ordered strongest to weakest, and the order is load-bearing: SPEC §9.3
    requires the identity anchor to degrade visibly, so every place that
    renders a binding renders which of these it rests on.

    ``self_declared`` is the weakest. It says only that whoever held the
    single-use code an admin issued for this number typed it into this handset
    — no line was proven. It exists because on this fleet the two proving
    routes are frequently both unavailable: Uzbek SIMs leave
    ``getLine1Number()`` empty, and the callback route needs a receiver line.
    Without it those handsets have no path to ``active`` at all, which is
    strictly worse: an unenrolled phone reports nothing, so nobody can even see
    that it is unverified. Governed by ``enrolment.allow_self_declared``.
    """

    SIM_MSISDN = "sim_msisdn"
    CALLBACK = "callback"
    ADMIN_ATTESTED = "admin_attested"
    SELF_DECLARED = "self_declared"


class VerificationState(StrEnum):
    """State of one verification attempt."""

    PENDING = "pending"
    MATCHED = "matched"
    FAILED = "failed"
    EXPIRED = "expired"
    ATTESTED = "attested"

    #: No line was proven; the code was accepted as the binding. Never written
    #: to ``number_verifications`` — there is no attempt to record — and only
    #: ever returned to the device so its screen can say which route finished.
    SELF_DECLARED = "self_declared"


class FunnelStage(StrEnum):
    """Where an agent is in the rollout (UC-17, SPEC §10.1).

    ``verified_by_admin`` is visibly distinct from ``number_verified`` because
    attested is weaker evidence than proven, and the identity anchor must never
    degrade silently (T142).
    """

    INVITED = "invited"
    INSTALLED = "installed"
    PERMITTED = "permitted"
    NUMBER_VERIFIED = "number_verified"
    VERIFIED_BY_ADMIN = "verified_by_admin"

    #: Enrolled on the strength of the code alone. Its own stage rather than
    #: ``number_verified`` so the rollout board cannot show an unproven binding
    #: as a proven one — an admin filters on this to know who still needs
    #: attesting.
    SELF_DECLARED = "self_declared"
    CAPTURING = "capturing"
    NEEDS_ASSISTED_INSTALL = "needs_assisted_install"
    INSTALL_DISAPPEARED = "install_disappeared"
    REVOKED = "revoked"


class Capability(StrEnum):
    """One row per installation per capability (UC-03, §7.8).

    Every one of these is verified by exercising it, never by reading a
    permission flag — that is what makes ``granted_not_working`` expressible.
    """

    PHONE_STATE = "phone_state"
    CALL_LOG = "call_log"
    MICROPHONE = "microphone"
    CONTACTS = "contacts"
    NOTIFICATIONS = "notifications"
    CALL_PHONE = "call_phone"
    BATTERY_EXEMPTION = "battery_exemption"
    STORAGE_ACCESS = "storage_access"
    OEM_AUTOSTART = "oem_autostart"
    FOREGROUND_SERVICE = "foreground_service"
    OEM_RECORDER = "oem_recorder"
    SUBSCRIPTION_RESOLUTION = "subscription_resolution"


class CapabilityState(StrEnum):
    """``granted_not_working`` is the OEM-permission-manager case UC-03 names."""

    GRANTED_WORKING = "granted_working"
    GRANTED_NOT_WORKING = "granted_not_working"
    DENIED = "denied"
    DENIED_PERMANENTLY = "denied_permanently"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class CommandKind(StrEnum):
    """Server-to-device commands. No ``send_sms`` — SMS is out of scope."""

    DIAL = "dial"
    CONFIG = "config"
    LOGOUT = "logout"
    PING = "ping"
    RECHECK = "recheck"


class CommandStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    EXPIRED = "expired"


class CommandFailureReason(StrEnum):
    """Why a command did not happen. UC-16 requires the panel to say which."""

    DEVICE_OFFLINE = "device_offline"
    NO_PERMISSION = "no_permission"
    OS_REFUSED = "os_refused"
    ACK_TIMEOUT = "ack_timeout"
    DISCARDED_STALE = "discarded_stale"
    UNSUPPORTED = "unsupported"
    BUSY = "busy"


class AlertKind(StrEnum):
    """Every cause that can raise an alert (SPEC §10.3).

    SPEC §3.1 says "24 values"; §10.3's table groups the three
    ``permission_lost_*`` causes on one line and pairs
    ``retention_job_failed``/``backup_failed`` on another. Expanded, the closed
    set is the 27 below — the count in §3.1 is a count of table rows.
    """

    CAPTURE_DISABLED = "capture_disabled"
    PERMISSION_LOST_MICROPHONE = "permission_lost_microphone"
    PERMISSION_LOST_PHONE_STATE = "permission_lost_phone_state"
    PERMISSION_LOST_CALL_LOG = "permission_lost_call_log"
    BATTERY_OPTIMISATION_REENABLED = "battery_optimisation_reenabled"
    APP_FORCE_STOPPED = "app_force_stopped"
    INSTALL_DISAPPEARED = "install_disappeared"
    RECORDING_ROUTE_LOST = "recording_route_lost"
    SERVICE_NOT_RUNNING = "service_not_running"
    DEVICE_OFFLINE = "device_offline"
    DEVICE_SILENT = "device_silent"
    FLEET_SILENT = "fleet_silent"
    CAPTURE_RATE_REGRESSION = "capture_rate_regression"
    QUEUE_FULL = "queue_full"
    STORAGE_LOW = "storage_low"
    POISONED_RECORD = "poisoned_record"
    AUTH_EXPIRED = "auth_expired"
    CREDENTIAL_REPLAY = "credential_replay"
    INSTALLATION_REBOUND = "installation_rebound"
    CALLBACK_RECEIVER_DOWN = "callback_receiver_down"
    ENROLMENT_STALLED = "enrolment_stalled"
    ATTRIBUTION_OUT_OF_RANGE = "attribution_out_of_range"
    ATTRIBUTION_DISCARDED_SPIKE = "attribution_discarded_spike"
    RETENTION_JOB_FAILED = "retention_job_failed"
    BACKUP_FAILED = "backup_failed"
    STORAGE_CAPACITY_LOW = "storage_capacity_low"
    MIN_VERSION_REFUSALS = "min_version_refusals"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActorType(StrEnum):
    """Who did the audited thing (SPEC §3.8)."""

    USER = "user"
    SERVICE = "service"
    DEVICE = "device"
    SYSTEM = "system"


class AuditAction(StrEnum):
    """Every auditable action (UC-24, N27).

    SPEC §3.16 was written against this set after the fact and added two values
    to it. Both earn their place by being separately *filterable*:

    * ``retention_changed`` is technically a ``setting_updated``, but it is the
      one setting whose change destroys data — "who shortened retention, and
      when" must be one filter, not a JSONB dig through every settings change.
    * ``command_issued`` is a person reaching into an employee's **personally
      owned** phone. It is the only action in the product that acts on somebody
      else's hardware, and this log is the only place that is visible.

    Adding a value is a migration, which is the point: the list is closed so
    that "everything that happened" is answerable from one column.
    """

    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DEACTIVATED = "user_deactivated"
    AGENT_CREATED = "agent_created"
    AGENT_UPDATED = "agent_updated"
    AGENT_ARCHIVED = "agent_archived"
    AGENTS_IMPORTED = "agents_imported"
    NUMBER_CREATED = "number_created"
    NUMBER_UPDATED = "number_updated"
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_CLOSED = "assignment_closed"
    CALLS_REATTRIBUTED = "calls_reattributed"
    ENROLMENT_CODE_ISSUED = "enrolment_code_issued"
    ENROLMENT_CODE_REVOKED = "enrolment_code_revoked"
    INSTALLATION_ATTESTED = "installation_attested"

    #: A handset bound itself to a number on the strength of its enrolment code
    #: alone. Audited because it is the one activation route with no proof
    #: behind it: if a binding is ever disputed, this is the row that says the
    #: number was never verified and names the phone that claimed it.
    INSTALLATION_SELF_DECLARED = "installation_self_declared"
    INSTALLATION_REVOKED = "installation_revoked"
    INSTALLATION_REBOUND = "installation_rebound"
    COMMAND_ISSUED = "command_issued"
    CALL_NOTE_UPDATED = "call_note_updated"
    CALLS_EXPORTED = "calls_exported"
    AUDIO_PLAY = "audio_play"
    AUDIO_DOWNLOAD = "audio_download"
    AUDIO_DELETED = "audio_deleted"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    SETTING_UPDATED = "setting_updated"
    RETENTION_CHANGED = "retention_changed"
    LINE_DIRECTORY_UPDATED = "line_directory_updated"
    SUPPORTED_MODEL_UPDATED = "supported_model_updated"
    APP_VERSION_UPLOADED = "app_version_uploaded"
    APP_VERSION_PUBLISHED = "app_version_published"
    SERVICE_TOKEN_CREATED = "service_token_created"
    SERVICE_TOKEN_REVOKED = "service_token_revoked"
    EXPORT_READ = "export_read"


class DirectoryRuleKind(StrEnum):
    """UC-25's ``*700`` is a ``suffix`` rule."""

    EXACT = "exact"
    PREFIX = "prefix"
    SUFFIX = "suffix"


class ReceiverKind(StrEnum):
    """The callback receiver is fleet-wide infrastructure (SPEC §9.4)."""

    GSM_GATEWAY = "gsm_gateway"
    ANDROID_RECEIVER = "android_receiver"


class ReceiverStatus(StrEnum):
    """No heartbeat for 3 min -> degraded, 5 min -> down + a critical alert."""

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


class UploadStatus(StrEnum):
    """Resumable audio upload session state (SPEC §4.5)."""

    OPEN = "open"
    COMMITTED = "committed"
    EXPIRED = "expired"
    ABORTED = "aborted"


class NetworkType(StrEnum):
    WIFI = "wifi"
    CELLULAR = "cellular"
    NONE = "none"


class EnrolmentAttemptKind(StrEnum):
    """``step_timing`` carries the per-screen durations that make N40 measurable."""

    CODE_REDEEM = "code_redeem"
    MSISDN_CHECK = "msisdn_check"
    CALLBACK_START = "callback_start"
    CALLBACK_MATCH = "callback_match"
    ADMIN_ATTEST = "admin_attest"
    STEP_TIMING = "step_timing"


class EnrolmentOutcome(StrEnum):
    """Every way an enrolment step can end. The funnel's evidence base."""

    OK = "ok"
    CODE_NOT_FOUND = "code_not_found"
    CODE_ALREADY_USED = "code_already_used"
    CODE_EXPIRED = "code_expired"
    CODE_REVOKED = "code_revoked"
    NUMBER_MISMATCH = "number_mismatch"
    MSISDN_EMPTY = "msisdn_empty"
    NO_CALLER_ID = "no_caller_id"
    TIMEOUT = "timeout"
    RECEIVER_DOWN = "receiver_down"
    ALREADY_BOUND = "already_bound"
    REJECTED = "rejected"


class AnalysisStage(StrEnum):
    """Where one call stands in the analysis pipeline (SPEC-ANALYTICS §2.4).

    The state row *is* the status: there is no ``calls.status`` column and
    nothing on ``calls`` is written by the analysis module.

    BonviZvonki's ``locked`` is deliberately absent. Locking is the claim query
    (``FOR UPDATE SKIP LOCKED``) plus the worker's advisory lock, and neither
    survives a crash — a persisted ``locked`` would, leaving a row that no
    dispatch picks up and no operator can explain.
    """

    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    SCORING = "scoring"
    COMPLETED = "completed"

    #: Deliberately not analysed. **Not a failure**, and the panel must not
    #: paint it as one: an internal call or a call with no recording is a
    #: normal outcome, and two of the reasons are re-checked by dispatch once
    #: the line directory fills.
    SKIPPED = "skipped"
    FAILED = "failed"


class AnalysisFailure(StrEnum):
    """Why a call stopped. Closed, and ``NOT NULL`` whenever the stage is
    ``skipped`` or ``failed`` (a CHECK on ``call_analysis_state``).

    ``stage`` says whether the row is terminal; this says why. The three groups
    below are not decoration — only the transient ones are re-queued by
    ``analysis_retry_transient``, and getting that membership wrong is how 885
    rate-limited calls stayed permanently failed in BonviZvonki after the quota
    they were waiting on had reset.
    """

    # --- Not analysable: a fact about the call, not about the run ----------
    NO_AUDIO = "no_audio"
    AUDIO_EXPIRED = "audio_expired"
    CALL_TOO_SHORT = "call_too_short"
    CALL_TYPE_UNKNOWN = "call_type_unknown"
    CALL_TYPE_INTERNAL = "call_type_internal"

    # --- Transient: the same call will succeed later -----------------------
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_COOLDOWN = "provider_cooldown"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_NETWORK = "provider_network"
    INTERRUPTED = "interrupted"
    TIMEOUT = "timeout"

    # --- Permanent: retrying buys the same answer at the same price --------
    TRANSCRIPT_EMPTY = "transcript_empty"
    SCORE_INVALID = "score_invalid"
    AI_NOT_CONFIGURED = "ai_not_configured"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_MODEL = "provider_model"
    SDK_MISSING = "sdk_missing"
    AUDIO_TOO_LARGE = "audio_too_large"

    #: The mapping of last resort for an exception nobody foresaw; the class
    #: name goes in ``failure_detail``. A closed enum with no such member would
    #: turn a surprise into a write error, which is the opposite of what a
    #: failure column is for.
    INTERNAL = "internal"


class AiRole(StrEnum):
    """Which half of the pipeline a provider is being asked to do.

    The primary key of ``ai_provider_cooldowns``, and therefore the unit a
    cooldown applies to: one account can serve both roles against different
    models and different quotas, and an exhausted ASR quota must not stop
    scoring transcripts that already exist.
    """

    ASR = "asr"
    LLM = "llm"


class CallSentiment(StrEnum):
    """The model's reading of how the conversation went."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class TranscriptQuality(StrEnum):
    """The model's own assessment of the transcript it was handed.

    A column rather than a derived value because the review rule reads it: a
    score computed from a transcript the model itself called ``low`` is one a
    person should look at before it reaches an employee's average.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


#: Every enum that becomes a PostgreSQL type, and the type name it takes.
#: The migration creates exactly these; a test asserts the two lists agree.
PG_ENUM_TYPES: dict[str, type[StrEnum]] = {
    "user_role": UserRole,
    "call_direction": CallDirection,
    "call_disposition": CallDisposition,
    "call_type": CallType,
    "call_source": CallSource,
    "audio_missing_reason": AudioMissingReason,
    "capture_route": CaptureRoute,
    "audio_codec": AudioCodec,
    "audio_container": AudioContainer,
    "app_variant": AppVariant,
    "installation_status": InstallationStatus,
    "verification_method": VerificationMethod,
    "verification_state": VerificationState,
    "funnel_stage": FunnelStage,
    "capability": Capability,
    "capability_state": CapabilityState,
    "command_kind": CommandKind,
    "command_status": CommandStatus,
    "command_failure_reason": CommandFailureReason,
    "alert_kind": AlertKind,
    "alert_severity": AlertSeverity,
    "actor_type": ActorType,
    "audit_action": AuditAction,
    "directory_rule_kind": DirectoryRuleKind,
    "receiver_kind": ReceiverKind,
    "receiver_status": ReceiverStatus,
    "upload_status": UploadStatus,
    "network_type": NetworkType,
    "enrolment_attempt_kind": EnrolmentAttemptKind,
    "enrolment_outcome": EnrolmentOutcome,
    "analysis_stage": AnalysisStage,
    "analysis_failure": AnalysisFailure,
    "ai_role": AiRole,
    "call_sentiment": CallSentiment,
    "transcript_quality": TranscriptQuality,
}

__all__ = ["PG_ENUM_TYPES", "pg_enum", *[cls.__name__ for cls in PG_ENUM_TYPES.values()]]
