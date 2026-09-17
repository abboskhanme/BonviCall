"""The provider domain — plain Python, bound to no vendor SDK.

Two things live here:

1. **The shared interface** (:class:`ASRClient`, :class:`LLMClient`) — calling
   code does NOT know which vendor is behind it. Swapping the provider does not
   move a single call site.
2. **The description of a provider** (:class:`AIProvider`) — one entry in the
   registry. Adding a vendor is writing one more of these.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.core.enums import AiRole

# --- Roles ------------------------------------------------------------------
# ASR: audio to text.   LLM: text to a score.
#
# Aliases of the enum rather than new string constants: ``AiRole`` is the
# PostgreSQL type behind ``ai_provider_cooldowns.role``, and a second spelling
# of "asr" is how a cooldown ends up written under a key nothing reads. It is a
# ``StrEnum``, so ``AiRole.ASR == "asr"`` and every dict keyed by the plain
# string keeps working.
ROLE_ASR = AiRole.ASR
ROLE_LLM = AiRole.LLM
AI_ROLES: tuple[str, ...] = (ROLE_ASR, ROLE_LLM)


# --- Transcript -------------------------------------------------------------


@dataclass(slots=True)
class TranscriptSegment:
    """One stretch of one speaker."""

    text: str
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None


@dataclass(slots=True)
class Transcript:
    """The ASR result — the same shape whichever provider produced it."""

    text: str
    provider: str
    model: str
    language: str | None = None
    duration_ms: int | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def has_diarization(self) -> bool:
        return any(s.speaker for s in self.segments)


# --- Client interfaces ------------------------------------------------------


@runtime_checkable
class ASRClient(Protocol):
    """Turns a stream of audio into text.

    ``audio`` is an ``AsyncIterator[bytes]``. It is NEVER written to disk: the
    stream is gathered in memory and handed straight to the provider.
    """

    provider_key: str
    model: str

    async def transcribe(
        self,
        audio: AsyncIterator[bytes],
        *,
        filename: str,
        language: str | None = None,
    ) -> Transcript: ...

    async def ping(self) -> str:
        """The cheapest real call there is — used to check the configuration."""
        ...


@runtime_checkable
class LLMClient(Protocol):
    """Produces text (or JSON) from text."""

    provider_key: str
    model: str

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> str: ...

    async def ping(self) -> str:
        """The cheapest real call there is — used to check the configuration."""
        ...


# --- The description of a provider ------------------------------------------


@dataclass(frozen=True, slots=True)
class AIProvider:
    """ONE entry in the registry.

    ``client_kind`` says which protocol it speaks. That is what makes adding an
    OpenAI-compatible vendor a change to no code at all:
    ``client_kind="openai_compat"`` plus a ``base_url`` is the whole of it.
    """

    key: str
    label: str
    roles: frozenset[str]
    models: dict[str, list[str]]
    defaults: dict[str, str]
    docs_url: str
    client_kind: str
    #: The vendor SDK package — the name shown in the error when it is missing
    sdk_package: str
    #: The name of the :class:`~src.core.config.Settings` FIELD holding the key,
    #: not the environment variable (SPEC-ANALYTICS §4.2). The key is read with
    #: ``getattr(get_settings(), settings_attr)``, because ``core/config.py`` is
    #: the one declared configuration surface and a value read around it would
    #: be missing from ``.env.example``.
    settings_attr: str
    #: Where an OpenAI-compatible provider lives (``None`` for official OpenAI)
    base_url: str | None = None

    def __post_init__(self) -> None:
        unknown = self.roles - set(AI_ROLES)
        if unknown:
            raise ValueError(f"{self.key}: unknown role {sorted(unknown)}")
        if not self.roles:
            raise ValueError(f"{self.key}: at least one role is required")
        for role in self.roles:
            if not self.defaults.get(role):
                raise ValueError(f"{self.key}: no default model for the {role!r} role")

    @property
    def env_var(self) -> str:
        """The environment variable behind :attr:`settings_attr`.

        Derived rather than stored so the two can never disagree:
        ``pydantic-settings`` is case-insensitive, so the field
        ``ai_gemini_api_key`` is filled from ``AI_GEMINI_API_KEY``. This is the
        name an operator is told when the key is blank, and telling them a name
        that is not in ``.env.example`` would be worse than saying nothing.
        """
        return self.settings_attr.upper()

    def supports(self, role: str) -> bool:
        return role in self.roles

    def default_model(self, role: str) -> str:
        return self.defaults[role]

    def suggested_models(self, role: str) -> list[str]:
        return list(self.models.get(role, ()))
