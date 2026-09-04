"""Structured logging with secret redaction (T16, N26, CONVENTIONS.md §9).

One rule, enforced by a processor rather than by remembering: **a token, a
password, an enrolment code or a verification code never appears in a log
line.** Values under a secret-bearing key are replaced by ``…`` plus their last
four characters, which is enough to correlate two log lines about the same
token and not enough to use it.

Naming rule that makes the redactor work, stated once because it is the sort of
thing that gets undone by accident: an enrolment or verification code is logged
under ``enrolment_code`` / ``verification_code``, **never** under ``code``.
``code`` is the error contract (``{"error":{"code":...}}``) and redacting it
would blind every failure log in the product.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

#: Keys whose value is a secret. Matching is case-insensitive and by substring,
#: so ``refresh_token_hash`` and ``X-Auth-Token`` are both caught.
SECRET_KEY_FRAGMENTS: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "credential",
        "secret",
        "authorization",
        "cookie",
        "enrolment_code",
        "verification_code",
        "api_key",
    }
)

#: Keys that contain one of the fragments above but are not secrets.
SECRET_KEY_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "token_version",
        "has_token",
        "password_changed_at",
        "must_change_password",
        # A boolean saying *whether* a password was generated. Redacting it
        # produced `password_generated=…`, which hides a useful fact and
        # teaches people that the log line is noise.
        "password_generated",
        "password_required",
    }
)

REDACTION_TAIL = 4


def redact(value: Any) -> Any:
    """``…`` plus the last four characters, for anything string-like."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if len(text) <= REDACTION_TAIL:
        return "…"
    return "…" + text[-REDACTION_TAIL:]


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in SECRET_KEY_EXCEPTIONS:
        return False
    return any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS)


def _redact_mapping(value: Any, depth: int = 0) -> Any:
    """Walk dicts and lists, redacting secret-bearing keys as it goes."""
    if depth > 6:  # a payload nested deeper than this is not worth walking
        return value
    if isinstance(value, dict):
        return {
            key: redact(item) if is_secret_key(str(key)) else _redact_mapping(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact_mapping(item, depth + 1) for item in value)
    return value


def redaction_processor(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor: redact every secret-bearing key in the event."""
    return {
        key: redact(item) if is_secret_key(str(key)) else _redact_mapping(item)
        for key, item in event_dict.items()
    }


def configure_logging(level: str = "INFO", environment: str = "dev") -> None:
    """Install the processor chain. Called once, from ``main.py``."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if environment == "prod"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redaction_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    """A bound logger. ``get_logger(__name__)`` at module level, as usual."""
    return structlog.get_logger(name)


__all__ = [
    "REDACTION_TAIL",
    "SECRET_KEY_EXCEPTIONS",
    "SECRET_KEY_FRAGMENTS",
    "configure_logging",
    "get_logger",
    "is_secret_key",
    "redact",
    "redaction_processor",
]
