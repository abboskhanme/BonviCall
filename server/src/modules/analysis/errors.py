"""Provider errors — a vendor exception becomes one named, redacted failure.

Two rules that are not negotiable, both ported from BonviZvonki with the
incidents that produced them:

1. **A key never reaches a message.** Vendor text passes through :func:`redact`
   before anything stores or logs it: the keys this deployment actually holds
   are cut by exact match, and key-shaped text by pattern. A live API key in a
   stack trace is a real incident (N26, CONVENTIONS.md §9).
2. **A 401 never shows the vendor's own text.** Some providers echo part of the
   key back in the body of an authentication failure.

**Why this hierarchy is not rooted in ``core.errors.AppError``.** Every
``AppError`` in this product lives in ``core/errors.py`` and describes the
answer to an HTTP request. These describe what a background job met while
talking to a vendor, and they are written to
``call_analysis_state.failure_code`` rather than returned to anybody
(SPEC-ANALYTICS §6.3). ``status_code`` survives anyway, because the retry logic
reads it by name to decide whether a call is worth repeating.

**Every ``code`` is an** :class:`~src.core.enums.AnalysisFailure` **member**, so
the pipeline stores ``exc.code`` directly and no second vocabulary exists. A 4xx
the vendor gave us that is neither authentication, nor an unknown model, nor a
quota falls to ``internal`` on purpose — that enum member's own docstring calls
itself the mapping of last resort for an exception nobody foresaw, and the class
name plus the redacted message go to ``failure_detail`` beside it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from src.core.config import get_settings
from src.core.enums import AnalysisFailure

# --- Removing secret values -------------------------------------------------

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"gsk_[A-Za-z0-9_\-]{12,}"),
    re.compile(r"xai-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bxi-api-key\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b(?:api[_\-]?key|authorization|bearer)\b\s*[:=]\s*\S+", re.IGNORECASE),
)

REDACTED = "[redacted]"


def configured_secrets() -> tuple[str, ...]:
    """Every vendor key this deployment actually holds (SPEC-ANALYTICS §4.2).

    Read through ``get_settings()`` rather than ``os.environ``: ``core/config``
    is the whole configuration surface, and a key read around it would be
    missing from ``.env.example`` and invisible when the value arrives from a
    Compose ``env_file``.

    Added to every :func:`redact` call rather than left to the call site: a
    redaction that depends on somebody remembering to pass the key is a
    redaction that fails on the one code path nobody reviewed. One key today,
    because phase 1 ships one provider — a vendor added later adds its line
    here and every existing log line is covered by that alone.
    """
    settings = get_settings()
    candidates = (settings.ai_gemini_api_key.get_secret_value(),)
    return tuple(value for value in candidates if value)


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove secret values from ``text``.

    ``secrets`` is whatever the caller knows about; the configured keys are
    added to it unconditionally. An exact match is cut first, then anything
    key-shaped.
    """
    cleaned = text or ""
    for secret in (*secrets, *configured_secrets()):
        if secret and len(secret) >= 6:
            cleaned = cleaned.replace(secret, REDACTED)
            # Some providers return the key abbreviated (sk-abc...xyz)
            cleaned = cleaned.replace(secret[:8], REDACTED)
            cleaned = cleaned.replace(secret[-8:], REDACTED)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned


def _short(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def human_delay(seconds: float) -> str:
    """Seconds as a duration a person can act on.

    An operator reading the failure detail needs "~30 minutes", not "1800
    seconds": the first is a number, the second is enough to decide whether to
    wait or to change the key.
    """
    seconds = max(0.0, float(seconds))
    if seconds >= 3600:
        return f"~{seconds / 3600:.1f} hours".replace(".0 ", " ")
    if seconds >= 90:
        return f"~{round(seconds / 60)} minutes"
    if seconds >= 1:
        return f"~{round(seconds)} seconds"
    return "a moment"


# --- The failures themselves ------------------------------------------------


class ProviderError(Exception):
    """Every provider failure, and the one nobody foresaw.

    ``code`` is what lands in ``call_analysis_state.failure_code``; ``message``
    is the redacted English text that lands beside it in ``failure_detail``.
    ``status_code`` is not an HTTP answer — it is how the retry logic reads
    "the vendor said 429" without re-parsing the vendor's exception.
    """

    status_code = 502
    code: str = AnalysisFailure.INTERNAL

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class ProviderConfigError(ProviderError):
    """Our configuration is wrong — the vendor is not at fault."""

    status_code = 409
    code = AnalysisFailure.AI_NOT_CONFIGURED


class ProviderDependencyError(ProviderError):
    """The vendor SDK is not installed."""

    status_code = 503
    code = AnalysisFailure.SDK_MISSING


class ProviderAuthError(ProviderError):
    code = AnalysisFailure.PROVIDER_AUTH


class ProviderModelError(ProviderError):
    code = AnalysisFailure.PROVIDER_MODEL


class ProviderRateLimitError(ProviderError):
    """429 — the vendor did NOT accept the request, and did not charge for it.

    Two extra fields, both of which the pipeline needs:

    * ``retry_after_sec`` — the wait the provider itself asked for (its
      ``Retry-After`` header, or Google's ``RetryInfo.retryDelay``). Without it
      ``with_backoff`` waits a blind 2/4/8/16 s: with the provider saying "retry
      in 25s" that is four early asks and four more 429s.

    * ``daily_quota`` — whether the limit is daily (or exhausted outright) or
      just a per-minute burst. The difference decides everything: a minute limit
      clears in seconds, a daily one does not clear until tomorrow. Measured:
      ``gemini-3.1-flash-lite`` allows 500 requests a day on the free tier, and
      once it is spent the vendor answers ``RESOURCE_EXHAUSTED`` with
      ``GenerateRequestsPerDayPerProjectPerModel-FreeTier`` — at which point
      every one of the 7,328 queued jobs retried, each re-fetching the audio.
    """

    status_code = 429
    code = AnalysisFailure.PROVIDER_RATE_LIMIT

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retry_after_sec: float | None = None,
        daily_quota: bool = False,
    ) -> None:
        super().__init__(message, code=code)
        self.retry_after_sec = retry_after_sec
        self.daily_quota = daily_quota


class ProviderRequestError(ProviderError):
    """A 4xx that is not authentication, not an unknown model, not a quota.

    Keeps the base ``internal`` code deliberately: the enum has no member for
    "the vendor rejected the request for a reason we have never seen", and
    inventing one would claim knowledge nobody has. The class name and the
    redacted vendor text go to ``failure_detail``.
    """


class AudioTooLargeError(ProviderRequestError):
    """The recording exceeded the ceiling before a byte reached the vendor."""

    code = AnalysisFailure.AUDIO_TOO_LARGE


class ProviderUnavailableError(ProviderError):
    code = AnalysisFailure.PROVIDER_UNAVAILABLE


class ProviderNetworkError(ProviderError):
    code = AnalysisFailure.PROVIDER_NETWORK


# --- Ready-made messages ----------------------------------------------------


def missing_key(provider_label: str, env_var: str) -> ProviderConfigError:
    return ProviderConfigError(
        f"No API key for {provider_label} — set {env_var} in the server "
        "environment and restart the backend"
    )


def unknown_provider(key: str, role: str, known: list[str]) -> ProviderConfigError:
    return ProviderConfigError(
        f"Unknown AI provider: {key!r}. Available for the {role!r} role: "
        + ", ".join(known)
    )


def role_not_supported(provider_label: str, role: str) -> ProviderConfigError:
    return ProviderConfigError(
        f"{provider_label} is not used for the {role!r} role — choose another "
        "provider in Settings"
    )


def sdk_missing(provider_label: str, package: str) -> ProviderDependencyError:
    return ProviderDependencyError(
        f"The {provider_label} library is not installed ({package}) — the "
        "backend image has to be rebuilt"
    )


def audio_too_large(limit_mb: int) -> AudioTooLargeError:
    return AudioTooLargeError(
        f"Audio is too large — over {limit_mb} MB, not processed"
    )


# --- Translating a vendor exception -----------------------------------------


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response: Any = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _message_of(exc: BaseException) -> str:
    for attr in ("message", "detail"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return str(exc)


def _is_network(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if any(token in name for token in ("timeout", "connect", "transport", "ssl")):
        return True
    module = type(exc).__module__.split(".")[0]
    if module in {"httpx", "httpcore", "aiohttp"} and _status_of(exc) is None:
        return True
    return isinstance(exc, OSError | ConnectionError | TimeoutError)


# --- The wait the provider ASKED for ----------------------------------------
#
# Why this is read rather than guessed. In a 429 the vendor almost always says
# when to come back, and we used to wait an exponential 2/4/8/16 seconds
# without reading it. That was wrong in both directions:
#
#   * ask too early and the attempt is spent on another 429;
#   * ask too late and a worker slot idles for nothing.
#
# Three sources, in order:
#   1. the ``Retry-After`` header (seconds or an HTTP date) — the standard;
#   2. ``RetryInfo.retryDelay`` — what Google returns ("25s");
#   3. the message text — "Please retry in 25.140473495s".
#
# The raw blob (``_raw_blob``) is used HERE ONLY, to find a number, and never
# reaches a message: it can contain a key (rule 1 at the top of this file).

#: "retryDelay: 25s", "retry_delay { seconds: 25 }", "'retryDelay': '25s'"
_RETRY_FIELD = re.compile(r"retry[_\-]?delay\D{0,16}(\d+(?:\.\d+)?)", re.IGNORECASE)

#: "Please retry in 25.14s", "try again in 500ms", "retry after 2 minutes"
_RETRY_PHRASE = re.compile(
    r"(?:retry|try again|wait)\s*(?:again)?\s*(?:in|after)\s*"
    r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)\b",
    re.IGNORECASE,
)


def _scale(unit: str) -> float:
    """Unit to a seconds multiplier. ``ms`` is tested BEFORE ``m``."""
    lowered = (unit or "s").lower()
    if lowered.startswith(("ms", "milli")):
        return 0.001
    if lowered.startswith("m"):  # m, min, minute
        return 60.0
    return 1.0


def _raw_blob(exc: BaseException) -> str:
    """The whole raw text of the error — headers, details, body.

    SDKs keep the detail in different places: ``google-genai`` in a ``details``
    dict, ``openai`` in ``body``, some only in ``str(exc)``. All three are
    searched together, or the pattern would be bound to one SDK version.
    """
    parts: list[str] = [str(exc), _message_of(exc)]
    for attr in ("details", "body", "response_json"):
        value = getattr(exc, attr, None)
        if value is not None:
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _from_header(exc: BaseException) -> float | None:
    """The ``Retry-After`` header: seconds or an HTTP date."""
    response: Any = getattr(exc, "response", None)
    headers: Any = getattr(response, "headers", None) or getattr(exc, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:  # noqa: BLE001 — headers need not be a mapping
        return None
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass

    # The HTTP-date form: "Wed, 21 Oct 2026 07:28:00 GMT"
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


def retry_after_sec(exc: BaseException) -> float | None:
    """The wait the provider asked for, in seconds. ``None`` if it said nothing.

    ``None`` and ``0.0`` MEAN DIFFERENT THINGS: the first is "the vendor was
    silent", the second is "ask again now". Hence the return type.
    """
    stated = _from_header(exc)
    if stated is not None:
        return stated

    blob = _raw_blob(exc)
    if not blob:
        return None

    match = _RETRY_FIELD.search(blob)
    if match:
        try:
            return max(0.0, float(match.group(1)))
        except ValueError:
            pass

    match = _RETRY_PHRASE.search(blob)
    if match:
        try:
            return max(0.0, float(match.group(1)) * _scale(match.group(2)))
        except ValueError:
            return None
    return None


#: Marks of a DAILY (or outright exhausted) quota.
#
# Google returns the quota identifier itself:
# ``GenerateRequestsPerDayPerProjectPerModel-FreeTier``. Other vendors put
# "per day" or "daily limit" in the text. Searched in the lower-cased blob.
_DAILY_QUOTA_HINTS = (
    "perday",
    "per day",
    "per-day",
    "per_day",
    "daily",
    "quota exceeded for quota metric",
)


def is_daily_quota(exc: BaseException) -> bool:
    """``True`` when the limit is daily, i.e. will not clear in seconds.

    This is a fundamentally different event from a per-minute burst. Waiting a
    little and continuing is right for a minute limit; once a daily quota is
    spent EVERY retry is wasted, because the vendor will not accept a single
    request until tomorrow. Not telling the two apart is why 858 calls were
    left permanently ``failed`` with ``ai_rate_limit`` in BonviZvonki.
    """
    blob = _raw_blob(exc).lower()
    if not blob:
        return False
    if any(hint in blob for hint in _DAILY_QUOTA_HINTS):
        return True
    # ``RESOURCE_EXHAUSTED`` plus the free-tier counter — Google's daily limit
    # arrives as exactly that pair
    return "resource_exhausted" in blob and "free_tier" in blob


#: Matched against the VENDOR's text, not against ours, which is why the
#: Russian word stays: it is a needle, not a message this product writes.
_MODEL_HINTS = ("model", "модель", "not_found", "does not exist", "unknown model")

#: Some providers (Gemini among them) answer an invalid key with 400 rather
#: than 401, so the text is checked as well as the status code.
_AUTH_HINTS = (
    "api key not valid",
    "invalid api key",
    "incorrect api key",
    "api_key_invalid",
    "invalid_api_key",
    "invalid authentication",
    "authentication_error",
    "unauthenticated",
    "unauthorized",
    "missing api key",
    "no api key",
)


def translate(
    exc: BaseException,
    *,
    provider_label: str,
    model: str,
    secrets: tuple[str, ...] = (),
) -> ProviderError:
    """Turn any vendor exception into a named, redacted :class:`ProviderError`."""
    if isinstance(exc, ProviderError):
        return exc

    if isinstance(exc, ModuleNotFoundError):
        return sdk_missing(provider_label, exc.name or "?")

    if _is_network(exc):
        return ProviderNetworkError(
            f"Could not reach the {provider_label} server — check the network "
            "or the provider address"
        )

    status = _status_of(exc)
    raw = _message_of(exc)
    detail = _short(redact(raw, secrets))
    lowered = raw.lower()

    if status in (401, 403) or any(hint in lowered for hint in _AUTH_HINTS):
        # The vendor text is withheld on purpose — it can contain the key
        return ProviderAuthError(
            f"The {provider_label} API key is wrong or revoked — replace it in "
            "the server environment"
        )

    if status == 404 or (
        status in (400, 422) and any(hint in lowered for hint in _MODEL_HINTS)
    ):
        return ProviderModelError(
            f"{provider_label} did not recognise the model {model!r} — check the "
            f"model name. The provider said: {detail}"
        )

    if status == 429:
        wait = retry_after_sec(exc)
        daily = is_daily_quota(exc)
        if daily:
            tail = "the daily quota is spent; no request is accepted until tomorrow"
        elif wait is not None:
            tail = f"the provider asked to wait {human_delay(wait)}"
        else:
            tail = "wait a little and try again"
        return ProviderRateLimitError(
            f"{provider_label} hit its request limit (429) — {tail}",
            retry_after_sec=wait,
            daily_quota=daily,
        )

    if status is not None and status >= 500:
        return ProviderUnavailableError(
            f"The {provider_label} server did not answer ({status}) — try later"
        )

    if status is not None and 400 <= status < 500:
        return ProviderRequestError(
            f"{provider_label} rejected the request ({status}): {detail}"
        )

    return ProviderError(f"Unexpected error talking to {provider_label}: {detail}")
