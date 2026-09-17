"""The common base for provider clients.

Everything here is vendor-independent:
  * :class:`ClientConfig` — all the factory hands a client;
  * gathering the audio stream in memory (NEVER onto disk);
  * a one-second silent WAV, for checking a key.
"""

from __future__ import annotations

import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from src.modules.analysis.errors import audio_too_large, translate
from src.modules.analysis.providers.types import AIProvider

#: A sane ceiling for one call. Anything larger is almost always a mistake.
#:
#: A SECOND line of defence here, not the first: BonviCall knows the size from
#: ``call_audio.bytes`` before a byte is read, so the pipeline refuses an
#: oversized recording without allocating anything (SPEC-ANALYTICS §3). This
#: guard still stands, because a stream that lies about its length is exactly
#: the case the pipeline's check cannot see.
MAX_AUDIO_MB = 200


@dataclass(slots=True)
class ClientConfig:
    """The minimum needed to build a client."""

    provider: AIProvider
    role: str
    model: str
    api_key: str
    #: Replaces the HTTP layer, for tests (``httpx.AsyncClient`` / ``MockTransport``)
    http_client: Any | None = None
    #: For SDKs that take ``async_client_args`` (google-genai)
    http_args: dict[str, Any] = field(default_factory=dict)
    timeout: float = 120.0

    @property
    def secrets(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


class BaseClient:
    """Shared error translation and identity."""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self.provider_key = config.provider.key
        self.model = config.model

    @property
    def label(self) -> str:
        return self._config.provider.label

    def _fail(self, exc: BaseException) -> Exception:
        return translate(
            exc,
            provider_label=self.label,
            model=self.model,
            secrets=self._config.secrets,
        )

    async def aclose(self) -> None:
        """Release whatever the vendor SDK is holding.

        **Not in the ported source, and added because the SDK made it
        necessary.** ``google-genai`` builds an ``httpx.AsyncClient`` per
        ``genai.Client`` and registers a finaliser that schedules ``aclose()``
        on garbage collection — which, with no loop left to run it, surfaces as
        "coroutine BaseApiClient.aclose was never awaited" and leaves a
        connection pool behind. One leak per scored call is nothing; a worker
        that scores for a week is a worker out of file descriptors.

        The default is a no-op, so a client that holds nothing needs no
        override and the pipeline can always call it.
        """
        return None

    async def list_models(self) -> list[str]:
        """The models the vendor offers RIGHT NOW, filtered to this role.

        Why a live list matters. Model names used to come from a list written
        by hand in code. When a vendor closed a model the list went stale, an
        admin picked something that did not work, and the error only appeared
        on the first scoring run — hours later. That happened: `gemini-2.5-pro`
        had been closed to new accounts while still standing as the default.

        An empty list means "the vendor did not say". The caller falls back to
        the registry's list rather than raising.
        """
        return []


async def collect_audio(
    audio: AsyncIterator[bytes], *, limit_mb: int = MAX_AUDIO_MB
) -> bytes:
    """Gather the stream IN MEMORY.

    Deliberately never written to disk: the recording already has exactly one
    home (``call_audio``), and a second copy on a provider client's temporary
    path is a copy no retention sweep knows about.
    """
    limit = limit_mb * 1024 * 1024
    buffer = bytearray()
    async for chunk in audio:
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise audio_too_large(limit_mb)
    return bytes(buffer)


def silence_wav(seconds: float = 1.0, sample_rate: int = 8000) -> bytes:
    """The cheapest audio there is — one second of silence (WAV, 16 kB).

    A real file is not needed: the provider only has to confirm that the key
    works.
    """
    frames = int(seconds * sample_rate)
    data = b"\x00\x00" * frames
    header = b"RIFF"
    header += struct.pack("<I", 36 + len(data))
    header += b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


def guess_mime(filename: str) -> str:
    lowered = (filename or "").lower()
    for suffix, mime in (
        (".mp3", "audio/mpeg"),
        (".m4a", "audio/mp4"),
        (".mp4", "audio/mp4"),
        (".wav", "audio/wav"),
        (".ogg", "audio/ogg"),
        (".opus", "audio/ogg"),
        (".flac", "audio/flac"),
        (".webm", "audio/webm"),
    ):
        if lowered.endswith(suffix):
            return mime
    return "audio/mpeg"
