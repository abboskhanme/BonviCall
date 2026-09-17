"""Telegram ``initData`` verification, and the router that uses it.

⚠️ **The router under test is not mounted** (``src/api/webapp/__init__.py``).
These tests mount it on a throwaway application, so the handler is exercised
without the real server serving it. That is the whole arrangement this port was
asked for, and the test that asserts it stays unmounted is at the bottom.

None of this opens a socket. Verifying ``initData`` is an HMAC over a string;
nothing is fetched from Telegram and the bot token is only ever an HMAC key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core import clock
from src.core.errors import UnauthorizedError
from src.modules.surveys import webapp

#: Only the two router tests are async; verification itself needs no loop.
BOT_TOKEN = "1234567:test-token-not-a-real-one"


def sign(fields: dict[str, str], token: str = BOT_TOKEN) -> str:
    """Build a genuinely signed ``initData`` string, the way Telegram does."""
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def init_fields(**overrides: str) -> dict[str, str]:
    base = {
        "auth_date": str(int(clock.now().timestamp())),
        "query_id": "AAA",
        "user": json.dumps({"id": 777, "first_name": "Mijoz"}),
        "start_param": "survey-token",
    }
    base.update(overrides)
    return base


# ── The happy path ─────────────────────────────────────────────────────────


def test_a_genuine_payload_verifies_and_yields_the_user_and_the_token() -> None:
    data = webapp.verify_init_data(sign(init_fields()), BOT_TOKEN)
    assert data.telegram_user_id == 777
    assert data.start_param == "survey-token"
    assert webapp.survey_token(data) == "survey-token"


def test_signature_stays_in_the_check_string() -> None:
    """⚠️ The subtlety that costs a day, and the reason it is a test.

    Newer Telegram clients add a ``signature`` field. Only ``hash`` is removed
    before the HMAC; strip ``signature`` as well and **every** genuine payload
    from a modern client fails — the door closes on everybody. Verified in the
    source against a real signed payload, and the reference implementations
    agree.
    """
    fields = init_fields(signature="an-opaque-ed25519-thing")
    data = webapp.verify_init_data(sign(fields), BOT_TOKEN)
    assert data.telegram_user_id == 777


# ── Refusals ───────────────────────────────────────────────────────────────


def test_no_bot_token_refuses_rather_than_passing_everything() -> None:
    """⚠️ Not a bypass, and the reason is arithmetic.

    With an empty token the HMAC key is derived from an empty string, so ANY
    forged payload a caller assembled would verify correctly. 503 rather than
    401: the caller's credentials are not the problem, this deployment is.
    """
    with pytest.raises(webapp.BotNotConfigured):
        webapp.verify_init_data(sign(init_fields()), None)
    with pytest.raises(webapp.BotNotConfigured):
        webapp.verify_init_data(sign(init_fields()), "")


def test_this_deployment_has_no_bot_token() -> None:
    """The fact the whole feature rests on. No token exists and none is asked for."""
    assert webapp.configured_bot_token() is None


def test_a_tampered_field_is_refused() -> None:
    raw = sign(init_fields())
    tampered = raw.replace("start_param=survey-token", "start_param=another-token")
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(tampered, BOT_TOKEN)


def test_a_payload_signed_with_another_token_is_refused() -> None:
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(sign(init_fields(), token="9999:other"), BOT_TOKEN)


def test_a_duplicate_key_is_refused() -> None:
    """⚠️ A forgery technique, not a typo: ``dict()`` keeps the LAST value while
    the check string covers BOTH, so one value gets signed and a different one
    gets read. The gap between those two is where the trick hides."""
    raw = sign(init_fields()) + "&start_param=smuggled"
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(raw, BOT_TOKEN)


def test_a_payload_without_a_hash_is_refused() -> None:
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(urlencode(init_fields()), BOT_TOKEN)


def test_an_oversized_payload_is_refused_before_any_hmac_is_computed() -> None:
    """Until the signature is verified we trust nobody, so the WORK is bounded
    too — otherwise an anonymous caller chooses how much hashing we do."""
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data("x" * (webapp.INIT_DATA_MAX_LEN + 1), BOT_TOKEN)


def test_stale_init_data_is_refused_even_though_the_signature_is_valid() -> None:
    """A link captured once must not keep working for ever."""
    stale = clock.now() - webapp.INIT_DATA_TTL - timedelta(minutes=1)
    fields = init_fields(auth_date=str(int(stale.timestamp())))
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(sign(fields), BOT_TOKEN)


def test_a_slightly_future_auth_date_is_forgiven() -> None:
    """The server clock may run a little ahead of Telegram's."""
    ahead = clock.now() + webapp.CLOCK_SKEW - timedelta(minutes=1)
    fields = init_fields(auth_date=str(int(ahead.timestamp())))
    assert webapp.verify_init_data(sign(fields), BOT_TOKEN).telegram_user_id == 777


def test_a_far_future_auth_date_is_refused() -> None:
    ahead = clock.now() + webapp.CLOCK_SKEW + timedelta(minutes=5)
    fields = init_fields(auth_date=str(int(ahead.timestamp())))
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(sign(fields), BOT_TOKEN)


@pytest.mark.parametrize(
    "user", ["", "not json", json.dumps({}), json.dumps({"id": 0}), json.dumps({"id": -3})]
)
def test_a_payload_without_a_usable_user_is_refused(user: str) -> None:
    with pytest.raises(UnauthorizedError):
        webapp.verify_init_data(sign(init_fields(user=user)), BOT_TOKEN)


def test_a_missing_start_param_is_a_404_not_a_401() -> None:
    """The signature was fine; there is simply no survey named."""
    from src.core.errors import NotFoundError

    fields = init_fields()
    del fields["start_param"]
    data = webapp.verify_init_data(sign(fields), BOT_TOKEN)
    with pytest.raises(NotFoundError):
        webapp.survey_token(data)


def test_every_refusal_says_the_same_thing() -> None:
    """⚠️ "No hash", "no user" and "signature mismatch" as separate messages
    would be free guidance to somebody assembling a forgery, one field at a
    time."""
    reasons = set()
    for raw in (
        urlencode(init_fields()),
        sign(init_fields(), token="9999:other"),
        sign(init_fields(user="")),
    ):
        try:
            webapp.verify_init_data(raw, BOT_TOKEN)
        except UnauthorizedError as refused:
            reasons.add((refused.code, str(refused.detail)))
    assert len(reasons) == 1


def test_the_telegram_id_never_reaches_a_traceback() -> None:
    """N26. A repr is how an identifier escapes without anybody deciding to let
    it — and this is the one identifier that could deanonymise a rating."""
    data = webapp.verify_init_data(sign(init_fields()), BOT_TOKEN)
    assert "777" not in repr(data)
    assert "redacted" in repr(data)


# ── The unmounted router ───────────────────────────────────────────────────


def _webapp_app(db) -> FastAPI:
    """Mount the unmounted router on a throwaway app, sharing the test session.

    The §9 error handlers are installed too. Without them an ``AppError``
    propagates as an unhandled exception and the test measures the absence of
    ``main.py`` rather than the behaviour of this router.
    """
    from src.api.webapp import router
    from src.core.deps import get_session
    from src.core.errors import AppError
    from src.main import app_error_handler

    application = FastAPI()
    application.include_router(router)
    application.add_exception_handler(AppError, app_error_handler)
    application.dependency_overrides[get_session] = lambda: db
    return application


@pytest.mark.asyncio
async def test_the_webapp_routes_refuse_because_there_is_no_bot(db) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_webapp_app(db)), base_url="http://testserver"
    ) as http:
        for path in ("/api/webapp/surveys/open", "/api/webapp/surveys/submit"):
            payload: dict[str, object] = {"init_data": sign(init_fields())}
            if path.endswith("submit"):
                payload |= {"csat": 5, "comment": None, "red_flags": []}
            response = await http.post(path, json=payload)
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_the_webapp_router_is_not_mounted_on_the_real_app(
    client: AsyncClient,
) -> None:
    """⚠️ The assertion that keeps this port's promise.

    Every route on that router is public and unauthenticated, its auth needs a
    bot token this deployment does not have, and nothing can hand a customer
    the deep link anyway. A mounted door nobody can be given a key to is attack
    surface and no more.
    """
    response = await client.post(
        "/api/webapp/surveys/open", json={"init_data": "anything"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
