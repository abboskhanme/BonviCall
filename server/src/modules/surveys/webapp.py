"""Verifying Telegram's ``initData`` (BonviZvonki ``surveys/application/webapp.py``).

This is the customer-facing door: a shop owner taps a button in their own
Telegram group and lands on a page that has no login. What authenticates them
is the signed blob Telegram hands the Mini App, and **this file is the whole of
that check**.

⚠️ **It makes no network call.** Verification is an HMAC over a string; nothing
is fetched from Telegram and nothing is sent to it. The bot token is a local
secret that is never transmitted — it is only ever used as an HMAC key.

⚠️ **Nothing in this deployment has a bot token**, so
:func:`verify_init_data` refuses everything with ``bot_not_configured``. That
refusal is deliberate and is NOT a bypass — see the check itself.

The whole module is ported because the reasoning in it was expensive to learn
and is not re-derivable from Telegram's documentation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl

from src.core import clock
from src.core.errors import AppError, ErrorCode, NotFoundError, UnauthorizedError

#: ``initData`` is around a kilobyte in practice. The cap is here because until
#: the signature is verified we trust nobody, so the WORK must be bounded too:
#: an unbounded string would mean computing an HMAC over whatever an anonymous
#: caller chose to send.
INIT_DATA_MAX_LEN = 4096

#: Stale ``initData`` is refused even when the signature is perfectly valid. A
#: link that was captured once must not keep working for ever.
INIT_DATA_TTL = timedelta(hours=24)

#: The server clock may run a little ahead of Telegram's. A future
#: ``auth_date`` inside this much is forgiven; beyond it, refused.
CLOCK_SKEW = timedelta(minutes=5)


class BotNotConfigured(AppError):
    """503 — there is no bot token, so nothing can be verified.

    ⚠️ **Deliberately a 503 and deliberately not a bypass.** With an empty
    token the HMAC key would be derived from an empty string, and *any* forged
    ``initData`` a caller assembled would then verify correctly. Refusing is
    the only safe answer, and refusing with 401 would be a lie — the caller's
    credentials are not the problem, this deployment is.

    This is the answer every request gets here today.
    """

    status_code = 503
    code = ErrorCode.CONFLICT


@dataclass(frozen=True)
class InitData:
    """What a verified ``initData`` yielded. Nothing else is kept."""

    telegram_user_id: int
    start_param: str | None
    auth_date: datetime

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        # ⚠️ The Telegram user id never reaches a log line or a traceback
        # (N26). It is the one identifier that could deanonymise a rating, and
        # a repr is the way it would escape without anyone deciding to let it.
        return f"InitData(telegram_user_id=<redacted>, start_param={self.start_param!r})"


def verify_init_data(raw: str, bot_token: str | None) -> InitData:
    """Verify Telegram's signature over ``raw`` and return what it carried.

    The scheme, from Telegram's Mini App documentation::

        secret_key        = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
        data_check_string = "\\n".join(sorted("k=v")), with `hash` removed
        expected          = HMAC_SHA256(key=secret_key, msg=data_check_string)

    ⚠️ **Only ``hash`` is stripped. ``signature`` STAYS IN the check string.**
    This is the subtlety that costs a day: newer Telegram clients add a
    ``signature`` field, and removing it as well makes every genuine
    ``initData`` fail. BonviZvonki verified this against a real signed payload
    — with only ``hash`` removed the digest matched; with ``hash`` and
    ``signature`` removed it did not — and the reference implementations agree
    (``@telegram-apps/init-data-node``'s ``validateFp``, ``init-data-golang``,
    aiogram's ``check_webapp_signature``). Strip ``signature`` too and this
    door is closed to everybody.

    ⚠️ **Every refusal raises the same generic 401.** "No hash", "no user" and
    "signature mismatch" as separate messages would be free guidance to
    somebody assembling a forgery, told one field at a time.
    """
    if not bot_token:
        raise BotNotConfigured(detail={"reason": "bot_not_configured"})
    if not raw or len(raw) > INIT_DATA_MAX_LEN:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"})

    try:
        pairs = parse_qsl(raw, strict_parsing=True, keep_blank_values=True)
    except ValueError as exc:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"}) from exc

    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        # ⚠️ A duplicate key is a forgery technique, not a typo. `dict()` keeps
        # the LAST value while the check string covers BOTH, so one value gets
        # signed and a different one gets read. The gap between those two is
        # exactly where the trick hides.
        raise UnauthorizedError(detail={"reason": "init_data_invalid"})

    fields = dict(pairs)
    supplied = fields.pop("hash", "")
    if not supplied:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"})

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret_key, check_string.encode(), hashlib.sha256
    ).hexdigest()

    # compare_digest, never `==`: a plain comparison stops at the first
    # differing byte, and the timing difference tells an attacker how many
    # leading bytes they got right.
    if not hmac.compare_digest(expected, supplied):
        raise UnauthorizedError(detail={"reason": "init_data_invalid"})

    auth_date = _auth_date(fields.get("auth_date"))
    now = clock.now()
    if auth_date < now - INIT_DATA_TTL or auth_date > now + CLOCK_SKEW:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"})

    return InitData(
        telegram_user_id=_user_id(fields.get("user")),
        start_param=fields.get("start_param") or None,
        auth_date=auth_date,
    )


def _auth_date(value: str | None) -> datetime:
    # `fromtimestamp`, not `now()` — §6's ban is on reading the clock outside
    # `core/clock.py`, and this converts a value the caller supplied.
    try:
        return datetime.fromtimestamp(int(value or ""), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"}) from exc


def _user_id(payload: str | None) -> int:
    """The Telegram id out of the signed ``user`` blob, and nothing else.

    It is read, hashed with the survey's token, and forgotten. It is never
    stored and never logged.
    """
    try:
        parsed = json.loads(payload or "")
        user_id = int(parsed["id"])
    except (TypeError, ValueError, KeyError) as exc:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"}) from exc
    if user_id <= 0:
        raise UnauthorizedError(detail={"reason": "init_data_invalid"})
    return user_id


def survey_token(data: InitData) -> str:
    """The survey token, out of ``start_param``.

    ⚠️ **The token is not a separate request field, and must never become
    one.** It travels inside ``initData`` so that Telegram's HMAC covers it. A
    token in the path or the body would let anyone pair their own genuine,
    correctly-signed ``initData`` with some other group's token and answer that
    group's survey.
    """
    if not data.start_param:
        raise NotFoundError(detail={"reason": "survey_not_found"})
    return data.start_param


def configured_bot_token() -> str | None:
    """The bot token for this deployment. **Always ``None``.**

    There is no Telegram bot here, no token exists, and none is being asked
    for. The accessor exists so that the one place a token would ever be read
    is a named function a reviewer can find, rather than a `getattr` buried in
    a router — and so that :func:`verify_init_data` reaches its
    ``bot_not_configured`` refusal by the normal path instead of by a special
    case.

    Wiring a real bot means returning a secret from ``core/config.py`` here.
    It does **not** go in ``app_settings``: ``settings:read`` is granted to
    every manager, so a key there is a key every manager can read — the rule
    ``core/settings_keys.py`` already states for the vendor API keys.
    """
    return None


__all__ = [
    "CLOCK_SKEW",
    "INIT_DATA_MAX_LEN",
    "INIT_DATA_TTL",
    "BotNotConfigured",
    "InitData",
    "configured_bot_token",
    "survey_token",
    "verify_init_data",
]
