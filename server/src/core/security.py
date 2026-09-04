"""Hashing, opaque tokens and JWTs — the primitives, not the policy.

Policy (who may log in, how long a token lives, what happens on replay) belongs
to ``modules/auth``. This module only knows how to turn a secret into something
safe to store and how to sign a claim set.

Two rules that are not negotiable:

* **A token is never stored, only its SHA-256.** A database dump, a backup tape
  or a support screenshot must not be replayable against the API.
* **Password verification never raises.** One corrupt hash must not 500 the
  login endpoint for everybody — that happened in BonviZvonki, where a bcrypt
  hash written by an older library raised ``pyo3_runtime.PanicException``, which
  does not even inherit from ``Exception``.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from jose import JWTError, jwt

from src.core import clock
from src.core.config import get_settings
from src.core.errors import ErrorCode, UnauthorizedError

#: argon2id with the library's defaults, which track the current OWASP advice.
_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"

#: SPEC §4.7: minimum 10 characters, no composition rule, no expiry, no history.
#: A rule people cannot follow is a rule they write on a sticky note.
MIN_PASSWORD_LENGTH = 10

#: Opaque refresh tokens are 32 bytes of entropy, URL-safe encoded.
OPAQUE_TOKEN_BYTES = 32


def hash_password(raw: str) -> str:
    """argon2id hash, safe to store."""
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """True when ``raw`` matches ``hashed``. Never raises.

    Broad by design: a malformed, truncated or foreign-format hash is a *wrong
    password*, not a server error. BonviZvonki learned this when one bad row
    took down every login.
    """
    try:
        return _hasher.verify(hashed, raw)
    except (Argon2Error, ValueError, TypeError):
        return False
    except BaseException:  # noqa: BLE001 - a hashing backend may panic, see the docstring
        return False


def needs_rehash(hashed: str) -> bool:
    """True when the stored hash uses parameters older than today's defaults."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except (Argon2Error, ValueError):
        return True


def sha256_hex(value: str) -> str:
    """The stored form of any bearer secret."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_opaque_token() -> str:
    """A refresh token, an installation secret, a service token."""
    return secrets.token_urlsafe(OPAQUE_TOKEN_BYTES)


def create_access_token(
    subject: uuid.UUID,
    token_type: str,
    expires_in: timedelta,
    claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    """Sign a JWT and return it with its expiry.

    ``typ`` is part of the payload, not a convention: a panel token and an
    installation token are both bearer strings and must not be interchangeable.
    """
    issued_at = clock.now()
    expires_at = issued_at + expires_in
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    payload.update(claims or {})
    secret = get_settings().secret_key.get_secret_value()
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify and decode, or raise 401 ``unauthorized``.

    Expiry, signature and malformed input all produce the same answer on the
    wire: telling a caller *which* of the three failed helps only the caller who
    should not have one.
    """
    secret = get_settings().secret_key.get_secret_value()
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedError(ErrorCode.UNAUTHORIZED) from exc


def bearer_token(header_value: str | None) -> str:
    """Pull the token out of an ``Authorization: Bearer …`` header."""
    if not header_value:
        raise UnauthorizedError()
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError()
    return token.strip()


__all__ = [
    "JWT_ALGORITHM",
    "MIN_PASSWORD_LENGTH",
    "bearer_token",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "needs_rehash",
    "new_opaque_token",
    "sha256_hex",
    "verify_password",
]
