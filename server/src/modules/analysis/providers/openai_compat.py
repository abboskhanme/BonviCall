"""Providers that speak the OpenAI protocol (through the official ``openai`` SDK).

This one module serves OpenAI itself and every vendor that copies its protocol
(DeepSeek, Together, Fireworks, xAI, Cerebras, Mistral...). They are added to
the registry with ``client_kind="openai_compat"`` and a ``base_url``, and no
code is touched.

**Phase 1 has no registry entry that uses it** (SPEC-ANALYTICS §4.1: the client
ruled OpenAI out and Claude is a later step). It comes across anyway because it
is the shared protocol ADAPTER rather than a vendor: the day an
OpenAI-compatible vendor is wanted, it is one registry row and a ``base_url``.

Note that it needs the ``openai`` package, which phase 1 deliberately does NOT
pin (§4.3). The import is inside :meth:`_build_sdk`, so this module imports
cleanly without it and only a call would raise — and in phase 1 nothing calls
it. Adding the vendor means adding the pin in the same change as the row.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from src.modules.analysis.errors import sdk_missing
from src.modules.analysis.providers.base import (
    BaseClient,
    collect_audio,
    guess_mime,
    silence_wav,
)
from src.modules.analysis.providers.types import Transcript, TranscriptSegment


class _OpenAIStyle(BaseClient):
    """The shared base for anything driven by the ``openai`` SDK."""

    sdk_package = "openai"

    def _build_sdk(self) -> Any:
        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError as exc:
            raise sdk_missing(self.label, self.sdk_package) from exc

        kwargs: dict[str, Any] = {
            "api_key": self._config.api_key,
            "timeout": self._config.timeout,
            "max_retries": 1,
        }
        if self._config.provider.base_url:
            kwargs["base_url"] = self._config.provider.base_url
        if self._config.http_client is not None:
            kwargs["http_client"] = self._config.http_client
        # The key is always passed explicitly and the argument must not be
        # "simplified" away: the SDK falls back to its own OPENAI_API_KEY
        # environment variable, and an unset key of ours would then silently
        # start billing whatever ambient key the host happens to carry (§4.2).
        return AsyncOpenAI(**kwargs)

    #: ``GET /v1/models`` does not say what MODALITY a model is — only the
    #: names. So the role is decided from the name pattern. The pattern is
    #: deliberately wide: leaving a doubtful model in the list beats hiding one
    #: that was needed (an admin tries it with the check button anyway).
    _ASR_HINTS = ("whisper", "transcribe", "audio", "speech-to-text")
    _LLM_SKIP = (
        "whisper", "transcribe", "tts", "embedding", "moderation",
        "dall-e", "image", "sora", "realtime", "audio",
    )

    async def list_models(self) -> list[str]:
        client = self._build_sdk()
        try:
            page = await client.models.list()
            raw = [str(getattr(m, "id", "") or "") for m in page.data]
        except Exception:  # noqa: BLE001 — no list means fall back to the registry
            return []

        asr = self._config.role == "asr"
        out = []
        for name in raw:
            low = name.lower()
            if not low:
                continue
            if asr:
                if any(h in low for h in self._ASR_HINTS):
                    out.append(name)
            elif not any(h in low for h in self._LLM_SKIP):
                out.append(name)
        return out


class OpenAICompatASRClient(_OpenAIStyle):
    """``POST /v1/audio/transcriptions`` (multipart)."""

    async def transcribe(
        self,
        audio: AsyncIterator[bytes],
        *,
        filename: str,
        language: str | None = None,
    ) -> Transcript:
        payload = await collect_audio(audio)
        return await self._transcribe_bytes(payload, filename, language)

    async def _transcribe_bytes(
        self, payload: bytes, filename: str, language: str | None
    ) -> Transcript:
        client = self._build_sdk()
        # ``verbose_json`` exists only in the whisper family — newer models
        # take ``json``, and asking for the other one answers 400
        verbose = "whisper" in self.model.lower()
        kwargs: dict[str, Any] = {
            "file": (filename, payload, guess_mime(filename)),
            "model": self.model,
            "response_format": "verbose_json" if verbose else "json",
        }
        if language:
            kwargs["language"] = language
        try:
            result = await client.audio.transcriptions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — translated into a ProviderError
            raise self._fail(exc) from None

        segments: list[TranscriptSegment] = []
        for raw in getattr(result, "segments", None) or ():
            segments.append(
                TranscriptSegment(
                    text=str(getattr(raw, "text", "") or "").strip(),
                    start_ms=_ms(getattr(raw, "start", None)),
                    end_ms=_ms(getattr(raw, "end", None)),
                )
            )
        return Transcript(
            text=(getattr(result, "text", "") or "").strip(),
            provider=self.provider_key,
            model=self.model,
            language=getattr(result, "language", None) or language,
            duration_ms=_ms(getattr(result, "duration", None)),
            segments=segments,
        )

    async def ping(self) -> str:
        transcript = await self._transcribe_bytes(silence_wav(), "ping.wav", None)
        return transcript.text or "(silence)"


class OpenAICompatLLMClient(_OpenAIStyle):
    """``POST /v1/chat/completions``."""

    #: Whether it supports a JSON schema directly (compatible vendors do not)
    supports_json_schema = True

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> str:
        client = self._build_sdk()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if schema:
            if self.supports_json_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": schema},
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}
                messages[0]["content"] = (
                    f"{system}\n\nReturn the answer in EXACTLY this JSON schema:\n"
                    + json.dumps(schema, ensure_ascii=False, sort_keys=True)
                )
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        return _first_text(response)

    async def ping(self) -> str:
        client = self._build_sdk()
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Reply: OK"}],
                max_tokens=8,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        return _first_text(response) or "OK"


def _first_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or ()
    for choice in choices:
        content = getattr(getattr(choice, "message", None), "content", None)
        if content:
            return str(content).strip()
    return ""


def _ms(value: Any) -> int | None:
    try:
        return int(float(value) * 1000)
    except (TypeError, ValueError):
        return None
