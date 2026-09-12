"""Application settings — one object, read once, from the environment.

Every key here exists in ``.env.example``. Adding a setting means adding it
there in the same commit: a key that only exists in code is a key the person
deploying this cannot know about.

Settings are read through :func:`get_settings` rather than a module-level
instance so that tests can point the process at ``bonvicall_test`` by setting
the environment before the first call (CONVENTIONS.md §13).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The whole of the server's configuration surface."""

    model_config = SettingsConfigDict(
        # Running in Docker the values arrive as real environment variables
        # (compose ``env_file``); running the suite on a developer machine the
        # repository-root ``.env`` is one level above ``server/``.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Environment -------------------------------------------------------
    environment: Literal["dev", "test", "prod"] = "dev"
    """Selects the log renderer and whether the interactive docs are served."""

    log_level: str = "INFO"
    tz: str = "Asia/Tashkent"
    """Container timezone. The business calendar itself is core/clock.TASHKENT."""

    # --- Database ----------------------------------------------------------
    postgres_user: str = "bonvicall"
    postgres_password: SecretStr = SecretStr("change_me")
    postgres_db: str = "bonvicall"
    postgres_test_db: str = "bonvicall_test"

    database_url: str = "postgresql+asyncpg://bonvicall:change_me@postgres:5432/bonvicall"
    """The dev/production database. Never used by the test suite."""

    test_database_url: str = (
        "postgresql+asyncpg://bonvicall:change_me@postgres:5432/bonvicall_test"
    )
    """A separate database, because BonviZvonki's test rows reached real users
    through a shared one (CONVENTIONS.md §13)."""

    # --- MoiZvonki (cloud telephony, T-MZ) ---------------------------------
    #
    # The provider whose own Android app does the capturing and whose cloud
    # holds the recording. BonviCall consumes it: a webhook per call event and
    # a periodic ``calls.list`` sweep for whatever the webhook missed. Ported
    # from the WunderkindLC integration, which is in production.
    #
    # Credentials live in the environment and NOT in ``app_settings``: the API
    # key is a secret, and ``app_settings`` is readable by every panel admin
    # and is rendered on a settings page (SPEC §3.8).
    moizvonki_enabled: bool = False
    moizvonki_domain: str = ""
    """The cabinet's subdomain — "bonvi" for bonvi.moizvonki.ru. A value
    containing a dot is used as-is, so a full host or a test proxy also works."""
    moizvonki_username: str = ""
    moizvonki_api_key: SecretStr = SecretStr("")
    moizvonki_webhook_secret: SecretStr = SecretStr("")
    """The secret path segment the provider posts to. It IS the authentication
    for that endpoint — the request arrives from the provider's servers with no
    token of ours — so it must be long and random, and a mismatch answers 404
    rather than 401 (never confirm the endpoint exists)."""

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- Auth --------------------------------------------------------------
    secret_key: SecretStr = SecretStr("change_me")
    """Signing key for panel and installation tokens. Refused in production
    while it still holds the placeholder — see :meth:`assert_production_ready`."""

    access_token_ttl_min: int = 30
    refresh_token_ttl_days: int = 90

    # --- Audio storage (core/storage.py) -----------------------------------
    audio_storage_path: Path = Path("/data/audio")
    release_storage_path: Path = Path("/data/releases")
    """Published APKs (N33). Separate from the audio tree on purpose: audio is
    customer data under a retention policy and a release must never be deleted
    by one."""

    apk_signing_sha256: str | None = None
    """SHA-256 fingerprint of the signing certificate, uppercase hex with or
    without colons. When set, publishing an APK signed by any other key is
    refused: Android will not install a differently-signed build as an update,
    only as an uninstall-and-reinstall, which destroys the phone's queue.
    Blank until the key is generated — see docs/APK-SIGNING.md."""
    audio_retention_months: int = 12
    """Bootstrap default only. Once the server runs, ``retention.audio_months``
    in ``app_settings`` is the value that decides (SPEC §3.8)."""

    # --- Mobile client version gate (N34) ----------------------------------
    min_supported_app_version: int = 1
    """Bootstrap default for ``app.min_supported_version_code``."""

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    def assert_production_ready(self) -> None:
        """Refuse to start in production with placeholder secrets.

        A server nobody can reach and a server with a published key are both
        deployment failures, and only one of them is loud. This makes the
        second one loud too.
        """
        if not self.is_production:
            return
        placeholders = [
            name
            for name, value in (
                ("SECRET_KEY", self.secret_key.get_secret_value()),
                ("POSTGRES_PASSWORD", self.postgres_password.get_secret_value()),
            )
            if value in ("", "change_me")
        ]
        if placeholders:
            raise RuntimeError(
                "Refusing to start in production with placeholder values for: "
                + ", ".join(placeholders)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings object."""
    return Settings()


__all__ = ["Settings", "get_settings"]
