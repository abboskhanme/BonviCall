"""THE AI PROVIDER REGISTRY.

==================================================================
  ADDING A PROVIDER = ADDING ONE ENTRY TO THIS LIST.
==================================================================

One entry produces, by itself:
  * the provider the factory resolves for a role (``analysis.asr_provider`` /
    ``analysis.llm_provider``);
  * the fallback model list;
  * the client, through ``client_kind``.

For vendors that speak the OpenAI protocol (DeepSeek, Together, Fireworks,
xAI, Cerebras, Mistral...) ``client_kind="openai_compat"`` plus a ``base_url``
is enough — no other line of code is touched.

**Phase 1 ships exactly one provider (SPEC-ANALYTICS §4.1): Gemini, for both
roles.** OpenAI is ruled out by the client. Claude returns later as one pinned
SDK, one key in ``core/config.py``, one entry here and one settings value — the
pipeline, the prompt, the scorer and the schema do not change, because the
provider is resolved per role at call time.
"""

from __future__ import annotations

from src.modules.analysis.providers.types import (
    AI_ROLES,
    ROLE_ASR,
    ROLE_LLM,
    AIProvider,
)

#
# GROQ (Whisper) WAS REMOVED — UNUSABLE FOR UZBEK.
#
# Tested on real calls (5 of them, 3-5 minutes each):
#   * `whisper-large-v3-turbo` with no language given -> the text came back
#     "translated" into English, or was read as Turkish;
#   * passing `language="uz"` MADE IT WORSE — nonsense syllables, with
#     Tibetan script mixed in;
#   * `whisper-large-v3` (the full model) behaved the same way.
# All five of the five calls scored 0.
#
# The cause is the model: the Whisper family effectively does not cover Uzbek.
# No setting fixes it, so keeping it in the list would only lead an admin into
# the wrong choice.
#
# ELEVENLABS was removed too — the client's decision. It was NOT tested here
# (there was no key), so we hold no evidence about its quality.
#
# If either is ever wanted back: restoring the entry is the whole change.
#
AI_PROVIDERS: list[AIProvider] = [
    AIProvider(
        key="gemini",
        label="Google Gemini",
        roles=frozenset({ROLE_ASR, ROLE_LLM}),
        # The 2.x family (`gemini-2.5-flash`, `gemini-2.5-pro`,
        # `gemini-2.0-flash`) is left out DELIBERATELY. It still appears in
        # `models.list`, but calling it on a NEW account returns "no longer
        # available to new users" — so the model in the suggestion list and in
        # the default value did not work, and the error only surfaced on the
        # first scoring run.
        # The order is the RECOMMENDED order — the first is the default.
        #
        # `gemini-3.1-flash-lite` leads because its free tier allows 500
        # requests a day (the flash family allows 20 — 25 times fewer, about
        # ten calls). Its quality was checked in testing: it transcribes Uzbek
        # speech accurately, separates the speakers, and gives the timestamps
        # in the shape the prompt asks for.
        #
        # `gemini-3.7-flash` is slightly more reliable at the rubric's
        # arithmetic (it miscounts less often), but its daily limit is very
        # tight.
        models={
            ROLE_ASR: [
                "gemini-3.1-flash-lite",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-flash-latest",
            ],
            ROLE_LLM: [
                "gemini-3.1-flash-lite",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-flash-latest",
            ],
        },
        defaults={
            ROLE_ASR: "gemini-3.1-flash-lite",
            ROLE_LLM: "gemini-3.1-flash-lite",
        },
        docs_url="https://ai.google.dev/gemini-api/docs",
        client_kind="gemini",
        sdk_package="google-genai",
        settings_attr="ai_gemini_api_key",
    ),
]

# --- Indexes ----------------------------------------------------------------

PROVIDERS_BY_KEY: dict[str, AIProvider] = {p.key: p for p in AI_PROVIDERS}


def _assert_unique() -> None:
    if len(PROVIDERS_BY_KEY) != len(AI_PROVIDERS):
        raise ValueError("the registry holds a duplicate provider key")
    seen: dict[str, str] = {}
    for provider in AI_PROVIDERS:
        owner = seen.get(provider.settings_attr)
        if owner:
            raise ValueError(
                f"{provider.settings_attr} is claimed twice: {owner} and {provider.key}"
            )
        seen[provider.settings_attr] = provider.key


_assert_unique()


def get_provider(key: str) -> AIProvider | None:
    return PROVIDERS_BY_KEY.get((key or "").strip())


def providers_for_role(role: str) -> list[AIProvider]:
    """The providers supporting this role, in registry order."""
    return [p for p in AI_PROVIDERS if p.supports(role)]


def default_provider_key(role: str) -> str:
    """The provider used when the setting is empty.

    Gemini for both roles in phase 1: it is the only ASR tested on real Uzbek
    calls that works, it takes audio directly, and having the same vendor score
    the transcript means one SDK, one key and one bill (§4.1).
    """
    candidates = providers_for_role(role)
    if not candidates:  # pragma: no cover — the registry cannot be empty
        raise ValueError(f"no provider for the {role!r} role")
    preferred = {ROLE_ASR: "gemini", ROLE_LLM: "gemini"}.get(role)
    for provider in candidates:
        if provider.key == preferred:
            return provider.key
    return candidates[0].key


def roles_summary() -> dict[str, list[str]]:
    """Diagnostics: role to provider keys."""
    return {role: [p.key for p in providers_for_role(role)] for role in AI_ROLES}
