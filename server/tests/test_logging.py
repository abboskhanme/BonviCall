"""Secret redaction in the log stream (T16, N26)."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from src.core.logging import (
    REDACTION_TAIL,
    configure_logging,
    is_secret_key,
    redact,
    redaction_processor,
)

SECRET = "eyJhbGciOiJIUzI1NiJ9.super-secret-value.9f2c"


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "access_token",
        "refresh_token",
        "refresh_token_hash",
        "Authorization",
        "Cookie",
        "credential_hash",
        "enrolment_code",
        "verification_code",
        "SECRET_KEY",
    ],
)
def test_secret_bearing_keys_are_recognised(key: str) -> None:
    assert is_secret_key(key)


@pytest.mark.parametrize(
    "key", ["code", "error_code", "token_version", "must_change_password", "call_id"]
)
def test_contract_keys_are_not_redacted(key: str) -> None:
    """``code`` is the error contract; redacting it would blind every failure log."""
    assert not is_secret_key(key)


def test_redaction_keeps_only_the_last_four_characters() -> None:
    """Enough to correlate two lines about one token, not enough to use it."""
    assert redact(SECRET) == "…" + SECRET[-REDACTION_TAIL:]
    assert redact("abc") == "…"
    assert redact(None) is None


def test_processor_redacts_nested_payloads() -> None:
    event = {
        "event": "enrolment_redeem",
        "enrolment_code": "K7M4PQ2X",
        "error_code": "enrolment_code_used",
        "device": {"model": "Redmi Note 12", "credential": SECRET},
        "headers": [{"Authorization": f"Bearer {SECRET}"}],
    }
    result = redaction_processor(None, "info", event)
    assert result["enrolment_code"] == "…PQ2X"
    assert result["error_code"] == "enrolment_code_used"
    assert result["device"]["model"] == "Redmi Note 12"
    assert SECRET not in json.dumps(result)


def test_no_token_reaches_the_log_stream(capsys: pytest.CaptureFixture[str]) -> None:
    """The N26 test the SPEC asks for: log a login, grep the output for the secret."""
    configure_logging(level="INFO", environment="prod")
    log = structlog.get_logger("test")
    log.info(
        "login",
        email="aziz@bonvi.uz",
        password="hunter2-correct-horse",
        access_token=SECRET,
        refresh_token=SECRET,
    )
    captured = capsys.readouterr().out
    assert "login" in captured
    assert SECRET not in captured
    assert "hunter2-correct-horse" not in captured
    assert "aziz@bonvi.uz" in captured, "redaction must not blind the useful half"
    # Leave logging in the state the rest of the suite expects.
    configure_logging(level="INFO", environment="dev")
    logging.getLogger().handlers.clear()
