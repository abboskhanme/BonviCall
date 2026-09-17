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

    # --- Call analysis (SPEC-ANALYTICS §4.6) ------------------------------
    #
    # Every value here is an int, a bool or a string: ``value_type`` decides
    # which editor the panel renders, and it has no float. BonviZvonki held
    # four of these as floats read from the environment; their defaults were
    # already whole numbers, so they are whole seconds here.
    #
    # The vendor API keys are NOT in this list and never will be.
    # ``settings:read`` is granted to manager, so a key in ``app_settings`` is
    # a key every manager can read — they live in ``core/config.py`` beside the
    # MoiZvonki credentials, for the reason stated there (§4.2).

    #: The feature flag, and the rollback. Seeded ``false``: deploying phase 1
    #: must be a no-op on the running system until somebody decides otherwise.
    #: With it off both jobs return 0 immediately and the run endpoint answers
    #: 409; rows already written stay readable.
    ANALYSIS_ENABLED: Final = "analysis.enabled"

    #: Registry key and model per role. An empty model falls back to the
    #: registry's default for that provider; an empty language means "provider,
    #: you detect it", which is deliberately legal for a multilingual fleet.
    ANALYSIS_ASR_PROVIDER: Final = "analysis.asr_provider"
    ANALYSIS_ASR_MODEL: Final = "analysis.asr_model"
    ANALYSIS_ASR_LANGUAGE: Final = "analysis.asr_language"
    ANALYSIS_LLM_PROVIDER: Final = "analysis.llm_provider"
    ANALYSIS_LLM_MODEL: Final = "analysis.llm_model"

    #: Below this many seconds a call is skipped as ``call_too_short``. Read in
    #: **both** the dispatch gate and the pre-run check, from this one key:
    #: BonviZvonki had two sources (30 from the environment, 10 from settings)
    #: and the button reported "0 calls" while the setting looked applied.
    ANALYSIS_MIN_DURATION_SEC: Final = "analysis.min_duration_sec"

    #: Are colleague-to-colleague calls transcribed? Off: phase 1 has no
    #: transcript search, so it would be an ASR bill for a feature that does
    #: not exist. Turning it on needs no deploy (§2.6, Q2).
    ANALYSIS_TRANSCRIBE_INTERNAL: Final = "analysis.transcribe_internal"

    #: How far back dispatch looks, on ``calls.received_at``. Seven days, not
    #: two: audio arrives after the call row (R7) and a handset that spent a
    #: weekend out of coverage has ``upload.session_ttl_days`` to deliver it. A
    #: 48-hour window would miss those recordings permanently and silently.
    ANALYSIS_LOOKBACK_HOURS: Final = "analysis.lookback_hours"

    #: Ceiling on one dispatch tick, so a backlog is not swallowed whole.
    ANALYSIS_MAX_CALLS_PER_RUN: Final = "analysis.max_calls_per_run"

    #: Calls in flight inside one ``analysis_run``.
    ANALYSIS_CONCURRENCY: Final = "analysis.concurrency"

    #: Requests per minute per role; ``0`` disables the limiter. The window is
    #: in-process and therefore exact rather than approximate, because the
    #: worker's advisory lock guarantees one ``analysis_run`` at a time (§5).
    ANALYSIS_ASR_RPM: Final = "analysis.asr_rpm"
    ANALYSIS_LLM_RPM: Final = "analysis.llm_rpm"

    #: Transient retries per provider call, and the exponential wait between
    #: them. A vendor-stated ``Retry-After`` always beats the guess.
    ANALYSIS_MAX_RETRIES: Final = "analysis.max_retries"
    ANALYSIS_BACKOFF_BASE_SEC: Final = "analysis.backoff_base_sec"
    ANALYSIS_BACKOFF_MAX_SEC: Final = "analysis.backoff_max_sec"

    #: A vendor asking for longer than this stops the stage instead of
    #: sleeping. Sleeping ten minutes inside a worker slot stalls the queue and
    #: reads from outside as a hung worker.
    ANALYSIS_MAX_WAIT_SEC: Final = "analysis.max_wait_sec"

    #: How long a role sits out after a **daily** quota. Half an hour rather
    #: than "until tomorrow": an admin may raise the tier or swap a key, and
    #: the system should notice that by itself.
    ANALYSIS_QUOTA_COOLDOWN_SEC: Final = "analysis.quota_cooldown_sec"

    #: Re-asks when the model's own arithmetic fails validation, with the error
    #: text appended. Two, not one: cheap models miscount block totals and
    #: usually fix it on the second ask, and the alternative is a paid-for call
    #: with no score at all.
    ANALYSIS_INVALID_RETRIES: Final = "analysis.invalid_retries"

    #: End-to-end ceiling for one call. ``analysis_stale_reset`` closes a row
    #: stuck in a running stage for twice this.
    ANALYSIS_CALL_TIMEOUT_SEC: Final = "analysis.call_timeout_sec"

    #: How far back the nightly transient retry reaches. BonviZvonki's window
    #: was the nightly run's own 48 hours, and 885 rate-limited calls stayed
    #: failed for ever because the quota reset the next day and nothing ever
    #: looked at them again.
    ANALYSIS_RETRY_TRANSIENT_DAYS: Final = "analysis.retry_transient_days"

    #: Two caps, because one of them can be zero (§4.5). The money cap is
    #: measured units x an admin-entered price, and that price starts unset —
    #: so on day one it is the call count that actually protects the account.
    ANALYSIS_MONTHLY_COST_CAP_MICRO_USD: Final = "analysis.monthly_cost_cap_micro_usd"
    ANALYSIS_MONTHLY_MAX_CALLS: Final = "analysis.monthly_max_calls"

    #: The vendors' prices, in micro-USD, entered by an admin after task 12
    #: measures real calls. ``0`` means **not priced**, never "free": while
    #: they are zero the status endpoint reports measured units and says so,
    #: rather than showing $0.00 (§11.1).
    ANALYSIS_PRICE_ASR_MICRO_USD_PER_MINUTE: Final = (
        "analysis.price_asr_micro_usd_per_minute"
    )
    ANALYSIS_PRICE_LLM_MICRO_USD_PER_1K_INPUT_TOKENS: Final = (
        "analysis.price_llm_micro_usd_per_1k_input_tokens"
    )
    ANALYSIS_PRICE_LLM_MICRO_USD_PER_1K_OUTPUT_TOKENS: Final = (
        "analysis.price_llm_micro_usd_per_1k_output_tokens"
    )

    # --- Customer satisfaction surveys (ported from BonviZvonki) -----------
    #
    # A survey is a message posted into a customer's Telegram group asking them
    # to rate the salesperson they dealt with. Nothing in this product can post
    # it: `modules/surveys/transport.py` ships a logging implementation and
    # there is no bot token. These keys are still real, because the panel
    # creates the rows and the rows are what a bot would later carry.

    #: The master switch, and the rollback. Seeded **false**.
    #:
    #: Off, no survey row is created at all: the broadcast button answers 409,
    #: the per-group send answers 409, and the cadence job returns 0 without
    #: touching a table. Rows already written stay readable, and the feedback
    #: page keeps working — reading what was collected is not sending.
    #:
    #: It is off for the same reason `analysis.enabled` is: this writes into
    #: chats real customers are sitting in, and deploying the feature must be a
    #: no-op on the running system until somebody decides otherwise.
    SURVEY_ENABLED: Final = "survey.enabled"

    #: May the cadence job queue surveys without a human pressing anything?
    #: Seeded **false**, and it is a SECOND switch rather than a mode of the
    #: first: `survey.enabled` asks "may surveys exist", this one asks "may
    #: they go out unattended". Writing to real customer groups automatically
    #: is a deliberate step and does not come free with turning the feature on.
    SURVEY_AUTO_SEND: Final = "survey.auto_send"

    #: Cadence: a group is asked at most once every this many days.
    SURVEY_PERIOD_DAYS: Final = "survey.period_days"

    #: Suppression: a group asked inside this window is not asked again.
    #: Separate from the cadence because the "send to everyone now" button
    #: bypasses this one and nothing else.
    SURVEY_SUPPRESSION_DAYS: Final = "survey.suppression_days"

    #: Answers needed before an average is shown at all. Below it the panel
    #: says "collecting" and the average is NULL rather than a number — one
    #: customer's bad morning must not become an employee's published score.
    #: Read through `rules.resolve_positive_int`, never as a constant: the
    #: setting that "looked applied" while the code compared against a
    #: hard-coded 5 is the defect this key exists to prevent.
    SURVEY_MIN_RESPONSES: Final = "survey.min_responses"

    #: How many hours the posted message stays in the group before the bot
    #: removes it, so a customer's chat does not become a notice board. `0`
    #: means never. Clamped to 47 by `rules.resolve_message_ttl_hours`:
    #: Telegram refuses to let a bot delete its own message after 48 hours, so
    #: a larger value promises a removal that cannot happen.
    SURVEY_MESSAGE_TTL_HOURS: Final = "survey.message_ttl_hours"

    #: What a salesperson may see of their own customer ratings:
    #: `hidden` | `score_only` | `full`. Seeded `score_only`.
    #:
    #: ⚠️ It does not control an item list, because there is never one for a
    #: salesperson: one group is one customer, so a single visible rating row
    #: identifies who wrote it, and the anonymity promise made in the customer's
    #: own chat outranks the setting. It decides between "this section is closed
    #: to you" (403) and "your average and your star distribution, no rows".
    ACCESS_SALES_CLIENT_RATING: Final = "access.sales_client_rating"

    # --- Sales control (the SAP register, revision 014) --------------------
    #
    # Every value here is an int, a bool or a string, for the reason stated
    # above the analysis block: ``value_type`` decides which editor the panel
    # renders and it has no float. The walk-in ticket limit is therefore whole
    # dollars, which is also the only precision anybody enters it in.

    #: R1's window, in whole Asia/Tashkent days — the sale day plus the N
    #: before it. A sale carries no clock (SAP gives only a date), so the
    #: window cannot be measured in hours. Clamped to 0..365 on read: ``99999``
    #: typed in here would switch the whole section off silently.
    SALES_WINDOW_DAYS: Final = "sales.window_days"

    #: The shared SAP codes walk-in buyers are booked under (`К00001` and
    #: friends — the К is Cyrillic). Under one of these "was this customer
    #: spoken to?" has no meaning: one code, a hundred people. **Never read as
    #: empty** — an empty set would flood the regular list with walk-in sales
    #: and blank the walk-in section, both silently — so an unreadable value
    #: falls back to the list pinned in ``modules/sales/rules.py``.
    SALES_WALK_IN_CODES: Final = "sales.walk_in_codes"

    #: The single-ticket limit for a walk-in sale, in whole dollars. It is the
    #: walk-in section's whole measure, because the rules cannot apply there.
    SALES_WALK_IN_LIMIT_USD: Final = "sales.walk_in_limit_usd"

    #: Our own departments' SAP codes — the convenient way to take a batch of
    #: contractors out of sales control. ⚠️ NOT a query filter: the list only
    #: FILLS ``sale_partners.excluded_at`` at the start of an import, and the
    #: control query reads the flag alone, so the button on the screen and the
    #: list in the settings can never contradict each other. **Empty is a real
    #: answer here** and is the default: falling back to a built-in list the
    #: way the walk-in codes do would quietly remove a real customer.
    SALES_INTERNAL_CODES: Final = "sales.internal_codes"

    #: The manager's daily Telegram digest. Seeded **false**, and it is the
    #: rollback as well as the switch: this is the one thing in the product
    #: that would leave the machine. It cannot in this repository — the only
    #: transport implementation logs what it would have sent
    #: (``modules/sales/telegram.py``) — but a feature that arrives already on
    #: is a feature nobody chose.
    SALES_DIGEST_ENABLED: Final = "sales.digest_enabled"

    #: Where the digest is addressed. Empty stops it, with a warning in the log
    #: rather than silence.
    SALES_DIGEST_CHAT_ID: Final = "sales.digest_chat_id"

    #: Sales below this many dollars are left out of the digest. ``0`` — all of
    #: them. A sale of UNKNOWN value is never excluded by it: "I do not know"
    #: is not "small".
    SALES_DIGEST_MIN_AMOUNT_USD: Final = "sales.digest_min_amount_usd"

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
