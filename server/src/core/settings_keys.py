"""Every settings key, as a constant (T58, SPEC §3.8).

**Nothing in the product hard-codes a threshold.** A value that is not a row in
``app_settings`` is a value nobody can change without a deploy, and this file
is what stops a module inventing a key name that then differs from the one the
migration seeded by a single character.

The defaults live in the migration, which is what seeds them; this file names
the keys and says what each one is for. A key here with no seeded row is a bug
the settings API refuses to start with — see ``test_every_key_is_seeded``.
"""

from __future__ import annotations

from typing import Final


class SettingKey:
    """The keys, grouped as SPEC §3.8 groups them."""

    # --- Retention and deletion (UC-26, N19) ------------------------------
    RETENTION_AUDIO_MONTHS: Final = "retention.audio_months"
    RETENTION_CONFIRM_BELOW_MONTHS: Final = "retention.confirm_below_months"
    RETENTION_CALLBACK_EVENTS_DAYS: Final = "retention.callback_events_days"

    # --- Alerting (UC-17, UC-23, UC-27, N4) -------------------------------
    ALERTS_DEVICE_OFFLINE_MINUTES: Final = "alerts.device_offline_minutes"
    ALERTS_SILENCE_HOURS: Final = "alerts.silence_hours"
    ALERTS_FLEET_SILENCE_HOURS: Final = "alerts.fleet_silence_hours"
    ALERTS_CAPTURE_REGRESSION_PP: Final = "alerts.capture_regression_pp"
    ALERTS_EMAIL_TO: Final = "alerts.email_to"

    # --- The app and its updates (N34) ------------------------------------
    APP_MIN_SUPPORTED_VERSION_CODE: Final = "app.min_supported_version_code"

    # --- Audio upload (§4.5) ----------------------------------------------
    UPLOAD_CHUNK_SIZE_BYTES: Final = "upload.chunk_size_bytes"
    UPLOAD_SESSION_TTL_DAYS: Final = "upload.session_ttl_days"
    UPLOAD_MAX_CHUNK_BYTES: Final = "upload.max_chunk_bytes"

    # --- The employee's data plan (N14, N15, N7) --------------------------
    DATA_CELLULAR_CAP_BYTES_MONTH: Final = "data.cellular_cap_bytes_month"
    DATA_DEFERRED_DAILY_CAP_BYTES: Final = "data.deferred_daily_cap_bytes"
    AUDIO_DEFER_TO_WIFI_HOURS: Final = "audio.defer_to_wifi_hours"

    # --- The employee's storage (N8, N10) ---------------------------------
    QUEUE_MAX_RECORDS: Final = "queue.max_records"
    QUEUE_MAX_AUDIO_BYTES: Final = "queue.max_audio_bytes"
    QUEUE_MIN_FREE_SPACE_BYTES: Final = "queue.min_free_space_bytes"

    # --- Device reporting cadence (UC-17, N42) ----------------------------
    DEVICE_HEARTBEAT_SECONDS: Final = "device.heartbeat_seconds"
    DEVICE_CAPABILITY_RECHECK_HOURS: Final = "device.capability_recheck_hours"
    DEVICE_CALL_LOG_SWEEP_HOURS: Final = "device.call_log_sweep_hours"

    # --- The business calendar (UC-27, N38, D-10) -------------------------
    WORKING_HOURS_START: Final = "working_hours.start"
    WORKING_HOURS_END: Final = "working_hours.end"
    WORKING_HOURS_TIMEZONE: Final = "working_hours.timezone"
    WORKING_HOURS_WORKDAYS: Final = "working_hours.workdays"
    WORKING_HOURS_HOLIDAYS: Final = "working_hours.holidays"

    # --- Enrolment (UC-01, §9.2) ------------------------------------------
    ENROLMENT_CODE_TTL_HOURS: Final = "enrolment.code_ttl_hours"
    ENROLMENT_CALLBACK_WINDOW_SECONDS: Final = "enrolment.callback_window_seconds"

    #: May a handset finish enrolment on the strength of the code alone, when
    #: neither proving route is available to it? Default ``true``: with it off
    #: and no callback receiver in service, no phone on this fleet can enrol at
    #: all. See ``VerificationMethod.SELF_DECLARED``.
    ENROLMENT_ALLOW_SELF_DECLARED: Final = "enrolment.allow_self_declared"

    #: Is the callback route part of THIS deployment? Default ``false``.
    #:
    #: The route needs a receiver — a GSM gateway or an Android handset on a
    #: known number — registered and heartbeating (SPEC §9.4). No deployment of
    #: this product has ever had one, so the panel's rollout page led with a
    #: red "nobody can enrol" banner about infrastructure that does not exist,
    #: while phones were enrolling perfectly well through the SIM, an admin's
    #: attestation, or the code alone.
    #:
    #: Off, the route is simply not offered: no banner, no receiver-health
    #: alert, and ``/verify/callback/start`` refuses. Turning it on is one row
    #: in ``app_settings`` — nothing was deleted, because the route is the
    #: strongest proof of a number this product has, and a fleet that installs
    #: a receiver should get it back with a setting rather than a release.
    ENROLMENT_CALLBACK_ENABLED: Final = "enrolment.callback_enabled"

    @classmethod
    def all(cls) -> frozenset[str]:
        return frozenset(
            value
            for name, value in vars(cls).items()
            if name.isupper() and isinstance(value, str)
        )


ALL_SETTING_KEYS: frozenset[str] = SettingKey.all()

#: Keys whose value a device is told and may act on. The heartbeat's ``config``
#: block carries these and nothing else — a phone has no business knowing the
#: retention period or who gets the alert e-mails.
DEVICE_VISIBLE_KEYS: frozenset[str] = frozenset(
    {
        SettingKey.UPLOAD_CHUNK_SIZE_BYTES,
        SettingKey.UPLOAD_MAX_CHUNK_BYTES,
        SettingKey.DATA_CELLULAR_CAP_BYTES_MONTH,
        SettingKey.DATA_DEFERRED_DAILY_CAP_BYTES,
        SettingKey.AUDIO_DEFER_TO_WIFI_HOURS,
        SettingKey.QUEUE_MAX_RECORDS,
        SettingKey.QUEUE_MAX_AUDIO_BYTES,
        SettingKey.QUEUE_MIN_FREE_SPACE_BYTES,
        SettingKey.DEVICE_HEARTBEAT_SECONDS,
        SettingKey.DEVICE_CAPABILITY_RECHECK_HOURS,
        SettingKey.DEVICE_CALL_LOG_SWEEP_HOURS,
    }
)

__all__ = ["ALL_SETTING_KEYS", "DEVICE_VISIBLE_KEYS", "SettingKey"]
