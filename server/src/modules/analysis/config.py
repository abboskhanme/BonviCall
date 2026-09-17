"""The pipeline's tuning knobs, read from ``app_settings`` (SPEC-ANALYTICS §4.6).

BonviZvonki read these from the environment, on the argument that vendor limits
and server capacity are DevOps values rather than admin ones. That argument does
not survive the move: ``core/settings_keys.py`` says in its own docstring that
**a value that is not a row in ``app_settings`` is a value nobody can change
without a deploy**, and every one of these decides either how much money the
feature may spend or how hard it leans on a vendor. Both are things somebody
needs to change at 22:00 without a release.

So ``from_env()`` is gone and :func:`load_config` reads the rows by
``SettingKey`` constant. The per-field reasoning came across with the fields,
because each number has an incident behind it.

Every value is an ``int``, a ``bool`` or a ``str``. BonviZvonki held four of
them as floats; here the settings table's ``value_type`` is one of
``int | bool | string | list | time`` and the panel renders the editor from it,
so the four became whole seconds. Their defaults were already whole numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.settings_keys import SettingKey
from src.modules.settings.service import SettingsService

#: How often the batch logs its rate. A logging cadence rather than a
#: threshold, so it stays a module constant and not a settings row: nothing
#: about the product changes when it moves.
PROGRESS_EVERY = 10


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """One snapshot of the settings, read once per job run.

    Frozen, and read **once at the top of a run** rather than per call: a
    setting changed halfway through a batch would otherwise apply to some calls
    and not others, and the resulting numbers would be unexplainable.
    """

    #: The feature flag (§4.4). False means both jobs return 0 immediately.
    enabled: bool

    #: Below this many seconds a call is ``call_too_short``. Read here and
    #: nowhere else, so the dispatch gate and the pre-run check cannot disagree
    #: — they did in BonviZvonki (30 from the environment, 10 from settings) and
    #: the button reported "0 calls" while the setting looked applied.
    min_duration_sec: int

    #: Are colleague-to-colleague calls transcribed? Off by default: phase 1 has
    #: no transcript search, so it would be an ASR bill for a feature that does
    #: not exist.
    transcribe_internal: bool

    #: How far back dispatch looks, on ``calls.received_at``. Seven days rather
    #: than two, because audio arrives after the call row and a handset that
    #: spent a weekend out of coverage still has its upload session.
    lookback_hours: int

    #: Ceiling on one dispatch tick, so a backlog is not swallowed whole.
    max_calls_per_run: int

    #: Calls in flight inside one ``analysis_run``.
    concurrency: int

    #: Requests per minute per role; ``0`` disables that limiter.
    asr_rpm: int
    llm_rpm: int

    #: Transient retries per provider call, and the wait between them. The wait
    #: doubles per attempt and carries jitter — without jitter every worker
    #: wakes at the same moment and collects the same 429 again.
    max_retries: int
    backoff_base_sec: int
    backoff_max_sec: int

    #: A vendor asking to wait longer than this stops the stage instead of
    #: sleeping. Sleeping ten minutes inside a worker slot stalls the queue and
    #: reads from outside as a hung worker.
    max_wait_sec: int

    #: How long a role sits out after a **daily** quota. Half an hour rather
    #: than "until tomorrow": an admin may raise the tier or swap the key, and
    #: the system should notice that by itself rather than waiting for midnight.
    quota_cooldown_sec: int

    #: Re-asks when the model's own arithmetic fails validation, with the error
    #: text appended. Two, not one: cheap models miscount block totals and
    #: usually fix it on the second ask. One call in five needed it, and the
    #: alternative is a paid-for call with no score at all.
    invalid_retries: int

    #: End-to-end ceiling for one call. ``analysis_stale_reset`` uses twice it.
    call_timeout_sec: int

    #: How far back the nightly transient retry reaches.
    retry_transient_days: int

    #: The two spend caps (§4.5). Both are checked before a call is claimed.
    monthly_cost_cap_micro_usd: int
    monthly_max_calls: int

    #: The vendors' prices, entered by an admin after task 12 measures real
    #: calls. ``0`` means **not priced** and never "free".
    price_asr_micro_usd_per_minute: int
    price_llm_micro_usd_per_1k_input_tokens: int
    price_llm_micro_usd_per_1k_output_tokens: int

    #: The language handed to the ASR provider. ``None`` is legal and means
    #: "you detect it" — deliberately allowed for a genuinely multilingual
    #: fleet, and measured as decisive for the Whisper family, which read Uzbek
    #: speech as Turkish and returned a translation instead of a transcript.
    asr_language: str | None

    @property
    def priced(self) -> bool:
        """Whether any price has been entered.

        The panel needs this to show measured units instead of ``$0.00``: a
        cost of zero because nobody typed a price is not a feature that is
        free (§11.1).
        """
        return any(
            (
                self.price_asr_micro_usd_per_minute,
                self.price_llm_micro_usd_per_1k_input_tokens,
                self.price_llm_micro_usd_per_1k_output_tokens,
            )
        )


async def load_config(session: AsyncSession) -> AnalysisConfig:
    """Read every ``analysis.*`` knob. Raises if a key is not seeded.

    Deliberately not defaulted: ``SettingsService.get`` raises on a missing key
    because SPEC §3.8 treats one as a bug in the migration rather than as a
    silent ``None``. A pipeline that quietly ran on made-up limits would be the
    worst of the available failures — it spends money.
    """
    settings = SettingsService(session)
    language = (await settings.get_str(SettingKey.ANALYSIS_ASR_LANGUAGE)).strip()
    return AnalysisConfig(
        enabled=await settings.get_bool(SettingKey.ANALYSIS_ENABLED),
        min_duration_sec=await settings.get_int(SettingKey.ANALYSIS_MIN_DURATION_SEC),
        transcribe_internal=await settings.get_bool(
            SettingKey.ANALYSIS_TRANSCRIBE_INTERNAL
        ),
        lookback_hours=await settings.get_int(SettingKey.ANALYSIS_LOOKBACK_HOURS),
        max_calls_per_run=await settings.get_int(SettingKey.ANALYSIS_MAX_CALLS_PER_RUN),
        concurrency=max(1, await settings.get_int(SettingKey.ANALYSIS_CONCURRENCY)),
        asr_rpm=await settings.get_int(SettingKey.ANALYSIS_ASR_RPM),
        llm_rpm=await settings.get_int(SettingKey.ANALYSIS_LLM_RPM),
        max_retries=await settings.get_int(SettingKey.ANALYSIS_MAX_RETRIES),
        backoff_base_sec=await settings.get_int(SettingKey.ANALYSIS_BACKOFF_BASE_SEC),
        backoff_max_sec=await settings.get_int(SettingKey.ANALYSIS_BACKOFF_MAX_SEC),
        max_wait_sec=await settings.get_int(SettingKey.ANALYSIS_MAX_WAIT_SEC),
        quota_cooldown_sec=await settings.get_int(
            SettingKey.ANALYSIS_QUOTA_COOLDOWN_SEC
        ),
        invalid_retries=await settings.get_int(SettingKey.ANALYSIS_INVALID_RETRIES),
        call_timeout_sec=await settings.get_int(SettingKey.ANALYSIS_CALL_TIMEOUT_SEC),
        retry_transient_days=await settings.get_int(
            SettingKey.ANALYSIS_RETRY_TRANSIENT_DAYS
        ),
        monthly_cost_cap_micro_usd=await settings.get_int(
            SettingKey.ANALYSIS_MONTHLY_COST_CAP_MICRO_USD
        ),
        monthly_max_calls=await settings.get_int(SettingKey.ANALYSIS_MONTHLY_MAX_CALLS),
        price_asr_micro_usd_per_minute=await settings.get_int(
            SettingKey.ANALYSIS_PRICE_ASR_MICRO_USD_PER_MINUTE
        ),
        price_llm_micro_usd_per_1k_input_tokens=await settings.get_int(
            SettingKey.ANALYSIS_PRICE_LLM_MICRO_USD_PER_1K_INPUT_TOKENS
        ),
        price_llm_micro_usd_per_1k_output_tokens=await settings.get_int(
            SettingKey.ANALYSIS_PRICE_LLM_MICRO_USD_PER_1K_OUTPUT_TOKENS
        ),
        # Empty is legal and means "provider, you detect it" (§4.6).
        asr_language=language or None,
    )
