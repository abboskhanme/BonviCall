"""Google Gemini, through the official ``google-genai`` SDK.

Gemini takes audio directly, which is why one provider covers both roles. For a
structured answer it is given ``response_mime_type="application/json"`` and the
schema is appended to the system instruction — that part does not depend on the
SDK version.

The SDK is imported inside :meth:`_build_sdk`, never at module level: a missing
package must be a clear error on the first call rather than a backend that
refuses to start.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from src.modules.analysis.errors import sdk_missing
from src.modules.analysis.providers.base import (
    BaseClient,
    ClientConfig,
    collect_audio,
    guess_mime,
    silence_wav,
)
from src.modules.analysis.providers.types import Transcript

#: Every line is asked for in EXACTLY this shape: "[MM:SS] SPEAKER_0: text".
#
#: **This constant stays in Uzbek, and it is the only Uzbek in this file**
#: (SPEC-ANALYTICS §1.2, §1.6). A model prompt is neither a comment nor a
#: message a person reads — it is domain data whose quality was measured on
#: real Uzbek and code-switched Uzbek/Russian speech. Translating it would be an
#: untested change to the most sensitive input this feature has.
#
#: The timestamp is not decoration: clicking a transcript line on the call page
#: seeks the audio to that second, and the red-flag markers are placed on the
#: timeline by these times. Neither works without them.
#
#: Nothing breaks when the model omits a time — the frontend still draws the
#: line, it just is not clickable.
#: WHY IT IS THIS LONG. A short instruction ("write every line like this") was
#: NOT enough: the model labelled the speaker for the first 8-10 lines, then
#: dropped the label and kept only the time. Out of a 151-line transcript only
#: 9 carried a label, and the page could not split the conversation into two
#: sides. Hence the worked example and the word "without exception".
_TRANSCRIBE_PROMPT = (
    "Ushbu telefon suhbatini so'zma-so'z matnga o'gir.\n\n"
    "QAT'IY SHAKL — har bir qator ISTISNOSIZ shunday bo'lsin:\n"
    "[MM:SS] SPEAKER_0: gap matni\n\n"
    "Namuna:\n"
    "[00:00] SPEAKER_0: Allo, assalomu alaykum.\n"
    "[00:03] SPEAKER_1: Vaalaykum assalom, eshitaman.\n"
    "[00:05] SPEAKER_0: Balon narxini bilmoqchi edim.\n"
    "[00:09] SPEAKER_0: Yuz ellik talikdan bormi?\n\n"
    "Qoidalar:\n"
    "1. HAR QATORDA vaqt ham, gapiruvchi ham bo'lishi SHART. "
    "Bitta odam ketma-ket bir necha gap aytsa ham, har qatorda uning "
    "yorlig'ini QAYTA yoz — yuqoridagi namunadagi oxirgi ikki qatorga "
    "qara.\n"
    "2. Gapiruvchilar faqat SPEAKER_0 va SPEAKER_1 (uchinchi ovoz "
    "bo'lsa SPEAKER_2). Ism o'rniga shu yorliqlarni ishlat.\n"
    "3. Vaqt — qator boshlangan payt, daqiqa:soniya.\n"
    "4. Faqat transkriptni qaytar: sarlavha, izoh, xulosa yozma."
)

#: Appended to the prompt above when the language is configured. Part of the
#: same Uzbek prompt, and exempt for the same reason.
_LANGUAGE_SUFFIX = " Audio tili: {language}."


class _GeminiBase(BaseClient):
    sdk_package = "google-genai"

    def __init__(self, config: ClientConfig) -> None:
        super().__init__(config)
        self._types: Any = None
        self._sdk: Any = None

    def _build_sdk(self) -> Any:
        """The SDK client, built once per provider client and then reused.

        The import is here, not at module level, so a missing package is a
        clear error on the first call rather than a backend that will not start.

        Memoised, which the ported source did not do: every ``genai.Client``
        owns an ``httpx.AsyncClient``, and transcribing one call used to build
        two of them — one for the ``types`` module and one inside
        ``_generate``. See :meth:`aclose`.
        """
        if self._sdk is not None:
            return self._sdk

        try:
            from google import genai
            from google.genai import types
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise sdk_missing(self.label, self.sdk_package) from exc

        self._types = types
        http_options: dict[str, Any] = {"timeout": int(self._config.timeout * 1000)}
        if self._config.provider.base_url:
            http_options["base_url"] = self._config.provider.base_url
        if self._config.http_args:
            # For tests: replacing the httpx transport
            http_options["async_client_args"] = dict(self._config.http_args)
            http_options["client_args"] = dict(self._config.http_args)
        self._sdk = genai.Client(
            api_key=self._config.api_key,
            http_options=types.HttpOptions(**http_options),
        )
        return self._sdk

    async def aclose(self) -> None:
        sdk, self._sdk = self._sdk, None
        if sdk is not None:
            await sdk.aio.aclose()

    #: Models dropped from the list, by name. They may support
    #: ``generateContent`` and still be useless to us: image, video, speech
    #: synthesis, embeddings, robotics, browser control and agent modes. An
    #: admin should see only CONVERSATION models — picking "deep-research" or
    #: "imagen" would fell the pipeline on its first call.
    _SKIP = (
        "embedding", "imagen", "veo", "lyria", "tts", "image",
        "robotics", "computer-use", "aqa", "antigravity",
        "deep-research", "live", "native-audio", "gemma",
        "nano-banana",  # an image model whose name does not contain "image"
    )

    #: OLD GENERATIONS — ``models.list`` STILL returns them, but calling one on
    #: a new account answers "This model is no longer available to new users".
    #: Google's own list cannot be trusted here: it says the model exists and
    #: the call then fails. Seen first-hand — this is why `gemini-2.5-pro` did
    #: not work.
    _RETIRED = ("gemini-1.", "gemini-2.")

    async def list_models(self) -> list[str]:
        client = self._build_sdk()
        names: list[str] = []
        try:
            for model in await client.aio.models.list():
                name = (getattr(model, "name", "") or "").split("/")[-1]
                low = name.lower()
                if not name or any(word in low for word in self._SKIP):
                    continue
                if low.startswith(self._RETIRED):
                    continue
                # ``supported_actions`` is what Google ITSELF says the model can
                # do. We do not guess: without ``generateContent`` our call
                # shape does not work on that model at all (Live API models, for
                # instance, only take ``bidiGenerateContent``).
                actions = getattr(model, "supported_actions", None) or []
                if "generateContent" not in actions:
                    continue
                names.append(name)
        except Exception:  # noqa: BLE001 — no list means fall back to the registry
            return []
        return names

    async def _generate(self, contents: Any, config: Any) -> str:
        client = self._build_sdk()
        try:
            response = await client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception as exc:  # noqa: BLE001 — translated into a ProviderError
            raise self._fail(exc) from None
        return (getattr(response, "text", None) or "").strip()


class GeminiASRClient(_GeminiBase):
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
        self._build_sdk()  # prepares ``types``
        types = self._types
        prompt = _TRANSCRIBE_PROMPT
        if language:
            prompt += _LANGUAGE_SUFFIX.format(language=language)
        contents = [
            types.Part.from_bytes(data=payload, mime_type=guess_mime(filename)),
            prompt,
        ]
        text = await self._generate(
            contents, types.GenerateContentConfig(temperature=0.0)
        )
        return Transcript(
            text=text,
            provider=self.provider_key,
            model=self.model,
            language=language,
        )

    async def ping(self) -> str:
        transcript = await self._transcribe_bytes(silence_wav(), "ping.wav", None)
        return transcript.text or "(silence)"


class GeminiLLMClient(_GeminiBase):
    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> str:
        self._build_sdk()
        types = self._types
        instruction = system
        options: dict[str, Any] = {
            "system_instruction": instruction,
            "max_output_tokens": max_tokens,
        }
        if schema:
            options["response_mime_type"] = "application/json"
            options["system_instruction"] = (
                f"{instruction}\n\nReturn the answer in EXACTLY this JSON schema:\n"
                + json.dumps(schema, ensure_ascii=False, sort_keys=True)
            )
        return await self._generate(user, types.GenerateContentConfig(**options))

    async def ping(self) -> str:
        self._build_sdk()
        types = self._types
        text = await self._generate(
            "Reply: OK", types.GenerateContentConfig(max_output_tokens=64)
        )
        return text or "OK"
