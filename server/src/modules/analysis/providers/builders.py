"""``client_kind`` to client class.

A registry entry says which protocol it speaks through ``client_kind``. That is
why adding an OpenAI-compatible vendor does not touch THIS FILE either — it
reuses the existing ``openai_compat`` row.

This module imports NO vendor SDK. An SDK is imported only when a client makes
a real call (``_build_sdk``), so the backend starts even with the vendor
library absent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.modules.analysis.providers.base import ClientConfig
from src.modules.analysis.providers.gemini import GeminiASRClient, GeminiLLMClient
from src.modules.analysis.providers.openai_compat import (
    OpenAICompatASRClient,
    OpenAICompatLLMClient,
)
from src.modules.analysis.providers.types import (
    AI_ROLES,
    ROLE_ASR,
    ROLE_LLM,
    AIProvider,
)
from src.modules.analysis.registry import AI_PROVIDERS

Builder = Callable[[ClientConfig], Any]

#: ``openai_compat`` has no registry row in phase 1 and is here anyway: it is
#: the shared protocol adapter, so an OpenAI-compatible vendor later is a
#: registry row and a ``base_url`` with no code. ``anthropic`` returns with
#: Claude, as one more row here and one more file beside it.
BUILDERS: dict[str, dict[str, Builder]] = {
    "openai_compat": {
        ROLE_ASR: OpenAICompatASRClient,
        ROLE_LLM: OpenAICompatLLMClient,
    },
    "gemini": {
        ROLE_ASR: GeminiASRClient,
        ROLE_LLM: GeminiLLMClient,
    },
}


def builder_for(provider: AIProvider, role: str) -> Builder:
    kind = BUILDERS.get(provider.client_kind)
    if kind is None:  # pragma: no cover — ``check_registry()`` prevents this
        raise KeyError(f"{provider.key}: unknown client_kind={provider.client_kind}")
    builder = kind.get(role)
    if builder is None:  # pragma: no cover
        raise KeyError(f"{provider.key}: no client for the {role!r} role")
    return builder


def check_registry() -> list[str]:
    """Check that the registry and the clients agree.

    An empty list means everything lines up. A test calls this.
    """
    problems: list[str] = []
    for provider in AI_PROVIDERS:
        kind = BUILDERS.get(provider.client_kind)
        if kind is None:
            problems.append(f"{provider.key}: no client_kind={provider.client_kind}")
            continue
        for role in AI_ROLES:
            if provider.supports(role) and role not in kind:
                problems.append(f"{provider.key}: no client for the {role!r} role")
    return problems
