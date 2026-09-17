"""The AI client factory.

Calling code knows only this::

    asr = await get_asr_client(session)
    llm = await get_llm_client(session)

Which vendor stands behind it is a settings row. Swapping the provider does not
move the call site.

Two sources, deliberately different (SPEC-ANALYTICS §4.2):

* **provider and model** come from ``app_settings``, because an admin changes
  them and the panel renders them;
* **the API key** comes from ``core/config.py``, because ``app_settings`` is
  served by ``GET /api/v1/settings`` behind ``settings:read``, which the
  registry grants to manager as well as admin. A key in that table is a key
  every manager can read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.settings_keys import SettingKey
from src.modules.analysis.errors import (
    missing_key,
    role_not_supported,
    unknown_provider,
)
from src.modules.analysis.providers.base import ClientConfig
from src.modules.analysis.providers.builders import builder_for
from src.modules.analysis.providers.types import (
    ROLE_ASR,
    ROLE_LLM,
    AIProvider,
    ASRClient,
    LLMClient,
)
from src.modules.analysis.registry import (
    default_provider_key,
    get_provider,
    providers_for_role,
)
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

#: The settings keys. Independent of the registry — the same two keys whichever
#: provider is chosen.
PROVIDER_SETTING = {
    ROLE_ASR: SettingKey.ANALYSIS_ASR_PROVIDER,
    ROLE_LLM: SettingKey.ANALYSIS_LLM_PROVIDER,
}
MODEL_SETTING = {
    ROLE_ASR: SettingKey.ANALYSIS_ASR_MODEL,
    ROLE_LLM: SettingKey.ANALYSIS_LLM_MODEL,
}


@dataclass(slots=True)
class AIResolution:
    """The current state, computed from the settings and the environment."""

    role: str
    provider: AIProvider
    model: str
    api_key: str


def _clean(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _api_key_of(provider: AIProvider) -> str:
    """The configured key for this provider, or ``""``.

    ``getattr`` on the settings object by the registry's ``settings_attr``, so
    a vendor added later needs no branch here — only its field in
    ``core/config.py`` and its line in ``.env.example``.
    """
    value = getattr(get_settings(), provider.settings_attr, None)
    if value is None:
        return ""
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return _clean(value)


def resolve_from_values(values: dict[str, Any], role: str) -> AIResolution:
    """Work out provider, model and key from the settings values.

    Touches no database, so it behaves identically in a test and at run time.
    ``values`` carries only what an admin can change; the key is read from the
    environment, never from this dict.
    """
    provider_key = _clean(values.get(PROVIDER_SETTING[role])) or default_provider_key(
        role
    )
    provider = get_provider(provider_key)
    if provider is None:
        raise unknown_provider(
            provider_key, role, [p.key for p in providers_for_role(role)]
        )
    if not provider.supports(role):
        raise role_not_supported(provider.label, role)

    model = _clean(values.get(MODEL_SETTING[role])) or provider.default_model(role)

    api_key = _api_key_of(provider)
    if not api_key:
        raise missing_key(provider.label, provider.env_var)

    return AIResolution(role=role, provider=provider, model=model, api_key=api_key)


async def resolve(session: AsyncSession, role: str) -> AIResolution:
    """Read the two settings rows for this role and resolve.

    Only the two keys for this role are read: ``SettingsService.get`` raises on
    a key that is not seeded, which is what SPEC §3.8 wants, and reading the
    whole table to find two values would make an unrelated missing row break
    scoring.
    """
    settings = SettingsService(session)
    values = {
        PROVIDER_SETTING[role]: await settings.get_str(PROVIDER_SETTING[role]),
        MODEL_SETTING[role]: await settings.get_str(MODEL_SETTING[role]),
    }
    resolution = resolve_from_values(values, role)
    # The key is never logged, and never will be: it is not in this record and
    # ``core/logging.py`` would redact an ``api_key`` field anyway (N26).
    log.debug(
        "ai_provider_resolved",
        role=str(role),
        provider=resolution.provider.key,
        model=resolution.model,
    )
    return resolution


def build_client(
    resolution: AIResolution,
    *,
    http_client: Any | None = None,
    http_args: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> Any:
    """Build the client. ``http_client`` / ``http_args`` are for tests only."""
    config = ClientConfig(
        provider=resolution.provider,
        role=resolution.role,
        model=resolution.model,
        api_key=resolution.api_key,
        http_client=http_client,
        http_args=dict(http_args or {}),
        timeout=timeout,
    )
    return builder_for(resolution.provider, resolution.role)(config)


async def get_asr_client(session: AsyncSession, **kwargs: Any) -> ASRClient:
    """The current ASR client. A missing key raises a named error."""
    return build_client(await resolve(session, ROLE_ASR), **kwargs)


async def get_llm_client(session: AsyncSession, **kwargs: Any) -> LLMClient:
    """The current LLM client. A missing key raises a named error."""
    return build_client(await resolve(session, ROLE_LLM), **kwargs)
