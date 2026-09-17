"""The provider layer, with NO API key and NO database (SPEC-ANALYTICS §10.4).

Three things are proved here:

1. **One call site, whichever vendor.** The registry, the builders and the
   client protocols agree, so ``build_client()`` returns something that
   satisfies ``ASRClient`` / ``LLMClient`` for every role every provider
   declares.
2. **The request shape.** ``httpx.MockTransport`` intercepts the call and hands
   back a canned answer, so the exact URL, headers and body the SDK produces
   are asserted rather than assumed. No key is needed and no byte leaves the
   machine — ``AI_GEMINI_API_KEY`` is unset in CI and these still pass.
3. **A key never reaches a message.** ``redact()`` is exercised against both a
   configured secret and a key-shaped pattern (N26).

Run with ``-s`` to see the requests that were sent::

    docker compose run --rm backend pytest src/modules/analysis/tests/test_providers.py -q -s
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from src.core.config import get_settings
from src.core.enums import AnalysisFailure
from src.modules.analysis.errors import (
    REDACTED,
    ProviderConfigError,
    ProviderError,
    audio_too_large,
    redact,
    translate,
)
from src.modules.analysis.factory import (
    MODEL_SETTING,
    PROVIDER_SETTING,
    build_client,
    resolve_from_values,
)
from src.modules.analysis.providers.base import MAX_AUDIO_MB, collect_audio, guess_mime
from src.modules.analysis.providers.builders import BUILDERS, check_registry
from src.modules.analysis.providers.types import (
    AI_ROLES,
    ROLE_ASR,
    ROLE_LLM,
    AIProvider,
    ASRClient,
    LLMClient,
)
from src.modules.analysis.registry import (
    AI_PROVIDERS,
    default_provider_key,
    providers_for_role,
)

FAKE_KEY = "sk-test-DO-NOT-USE-0123456789abcdef"

#: A defect in ``google-genai`` 2.24.0, not in this code, and narrow on purpose
#: so nothing else is hidden: ``BaseApiClient.__del__`` schedules ``aclose()``
#: on garbage collection WHETHER OR NOT the client was already closed, and the
#: task it creates is destroyed with the test's event loop. The real leak — the
#: connection pool — is closed by :meth:`BaseClient.aclose`, and
#: ``test_one_sdk_client_per_provider_client_and_it_can_be_closed`` is what
#: proves it, so this filter can never hide one going unclosed.
pytestmark = pytest.mark.filterwarnings(
    r"ignore:coroutine 'BaseApiClient\.aclose' was never awaited:RuntimeWarning"
)


@pytest.fixture
def configured_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """A fake key on the settings object, for the length of one test.

    ``get_settings()`` is ``lru_cache``d, so this patches the one instance the
    factory reads and pytest puts the real (empty) value back afterwards. This
    is what makes "no API key required to run the suite" true.
    """
    monkeypatch.setattr(get_settings(), "ai_gemini_api_key", SecretStr(FAKE_KEY))
    return FAKE_KEY


# --- Canned vendor answers --------------------------------------------------

GEMINI_JSON = {
    "candidates": [
        {
            "content": {"parts": [{"text": "OK"}], "role": "model"},
            "finishReason": "STOP",
            "index": 0,
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 1,
        "candidatesTokenCount": 1,
        "totalTokenCount": 2,
    },
}


class Recorder:
    """Records the request and answers with something canned."""

    def __init__(self, payload: Any, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.request: httpx.Request | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        request.read()
        return httpx.Response(self.status, json=self.payload)

    @property
    def body(self) -> str:
        assert self.request is not None
        return self.request.content.decode("utf-8", errors="replace")

    def dump(self, title: str) -> None:
        assert self.request is not None, "no request was sent at all"
        req = self.request
        interesting = {
            k: v
            for k, v in req.headers.items()
            if k.lower() in {"authorization", "x-api-key", "x-goog-api-key", "content-type"}
        }
        safe = {k: ("<KEY>" if FAKE_KEY in v else v[:60]) for k, v in interesting.items()}
        print(f"\n-- {title}")
        print(f"   {req.method} {req.url}")
        print(f"   headers: {safe}")
        print(f"   body: {self.body[:400]}")


def _client(provider: str, role: str, recorder: Recorder, model: str = "") -> Any:
    values = {PROVIDER_SETTING[role]: provider, MODEL_SETTING[role]: model}
    resolution = resolve_from_values(values, role)
    transport = httpx.MockTransport(recorder.handler)
    if provider == "gemini":
        # google-genai builds its own httpx client, so the transport is handed
        # to it rather than the client being replaced
        return build_client(resolution, http_args={"transport": transport})
    return build_client(resolution, http_client=httpx.AsyncClient(transport=transport))


async def _silence():
    yield b"\x00" * 32


# --- 1. The registry, the builders and the protocols agree ------------------


def test_registry_and_builders_agree() -> None:
    """The check that makes "adding a vendor is adding a row" true."""
    assert check_registry() == []


def test_phase_one_ships_exactly_one_provider() -> None:
    """§4.1: Gemini, both roles. A second row is a decision, not a drift."""
    assert [p.key for p in AI_PROVIDERS] == ["gemini"]
    for role in AI_ROLES:
        assert default_provider_key(role) == "gemini"
        assert [p.key for p in providers_for_role(role)] == ["gemini"]


def test_the_shared_adapter_survives_without_a_vendor_row() -> None:
    """``openai_compat`` has no registry row and is still wired.

    That is the property §4.1 buys: an OpenAI-compatible vendor later is a
    registry row and a ``base_url``, with no code. Deleting this entry because
    "nothing uses it" is what would break that.
    """
    assert set(BUILDERS["openai_compat"]) == {ROLE_ASR, ROLE_LLM}
    assert "openai_compat" not in {p.client_kind for p in AI_PROVIDERS}


@pytest.mark.parametrize(
    ("provider_key", "role"),
    [(p.key, role) for p in AI_PROVIDERS for role in sorted(p.roles)],
)
def test_every_provider_resolves_for_every_declared_role(
    provider_key: str, role: str, configured_key: str
) -> None:
    values = {PROVIDER_SETTING[role]: provider_key, MODEL_SETTING[role]: ""}
    resolution = resolve_from_values(values, role)
    assert resolution.provider.key == provider_key
    assert resolution.model == resolution.provider.default_model(role)
    assert resolution.api_key == configured_key

    client = build_client(resolution)
    assert client.provider_key == provider_key
    assert client.model == resolution.model
    protocol = ASRClient if role == ROLE_ASR else LLMClient
    assert isinstance(client, protocol), f"{provider_key}/{role} does not fit the protocol"


def test_the_default_model_is_one_of_the_suggested_ones() -> None:
    for provider in AI_PROVIDERS:
        for role in sorted(provider.roles):
            assert provider.default_model(role) in provider.suggested_models(role)


def test_admin_typed_model_wins_over_the_default(configured_key: str) -> None:
    """A model the vendor shipped this morning must be usable this morning."""
    values = {
        PROVIDER_SETTING[ROLE_LLM]: "gemini",
        MODEL_SETTING[ROLE_LLM]: "gemini-4-preview-xyz",
    }
    assert resolve_from_values(values, ROLE_LLM).model == "gemini-4-preview-xyz"


def test_empty_provider_falls_back_to_the_registry_default(configured_key: str) -> None:
    assert resolve_from_values({}, ROLE_LLM).provider.key == "gemini"
    assert resolve_from_values({}, ROLE_ASR).provider.key == "gemini"


# --- 2. Configuration failures name what is wrong ---------------------------


def test_missing_key_names_the_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key configured — and the message says which variable to set.

    The blank key is set explicitly rather than relied upon: this suite must
    behave identically on a developer machine that happens to carry a real
    ``AI_GEMINI_API_KEY`` in its ``.env``.
    """
    monkeypatch.setattr(get_settings(), "ai_gemini_api_key", SecretStr(""))
    with pytest.raises(ProviderConfigError) as excinfo:
        resolve_from_values({PROVIDER_SETTING[ROLE_ASR]: "gemini"}, ROLE_ASR)
    message = excinfo.value.message
    assert "AI_GEMINI_API_KEY" in message
    assert "Google Gemini" in message
    assert excinfo.value.code == AnalysisFailure.AI_NOT_CONFIGURED


def test_a_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ai_gemini_api_key", SecretStr("   "))
    with pytest.raises(ProviderConfigError):
        resolve_from_values({PROVIDER_SETTING[ROLE_LLM]: "gemini"}, ROLE_LLM)


def test_unknown_provider_fails_clearly(configured_key: str) -> None:
    with pytest.raises(ProviderConfigError) as excinfo:
        resolve_from_values({PROVIDER_SETTING[ROLE_LLM]: "skynet"}, ROLE_LLM)
    message = excinfo.value.message
    assert "skynet" in message
    for provider in providers_for_role(ROLE_LLM):
        assert provider.key in message


def test_provider_without_the_role_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, configured_key: str
) -> None:
    """The message names the provider and the role, not "invalid config".

    Phase 1's single provider declares both roles, so the case is built rather
    than found: a text-only vendor is exactly what Claude will be, and the
    branch has to work on the day its row is added, not be written then.
    """
    from src.modules.analysis import registry

    llm_only = AIProvider(
        key="text-only",
        label="Text Only Vendor",
        roles=frozenset({ROLE_LLM}),
        models={ROLE_LLM: ["m"]},
        defaults={ROLE_LLM: "m"},
        docs_url="https://example.invalid",
        client_kind="openai_compat",
        sdk_package="openai",
        settings_attr="ai_gemini_api_key",
    )
    monkeypatch.setitem(registry.PROVIDERS_BY_KEY, llm_only.key, llm_only)

    with pytest.raises(ProviderConfigError) as excinfo:
        resolve_from_values({PROVIDER_SETTING[ROLE_ASR]: llm_only.key}, ROLE_ASR)
    assert "Text Only Vendor" in excinfo.value.message
    assert "asr" in excinfo.value.message
    # ...and it resolves perfectly well for the role it does declare
    assert resolve_from_values(
        {PROVIDER_SETTING[ROLE_LLM]: llm_only.key}, ROLE_LLM
    ).model == "m"


def test_the_env_var_is_derived_from_the_settings_field() -> None:
    """§4.2: the registry names the ``Settings`` FIELD, not the variable.

    Derived rather than stored, so the name an operator is told is always the
    name ``pydantic-settings`` actually reads.
    """
    for provider in AI_PROVIDERS:
        assert hasattr(get_settings(), provider.settings_attr)
        assert provider.env_var == provider.settings_attr.upper()


# --- 3. The request shape, per provider, with no key ------------------------


@pytest.mark.asyncio
async def test_gemini_asr_request_shape(configured_key: str) -> None:
    rec = Recorder(GEMINI_JSON)
    client = _client("gemini", ROLE_ASR, rec)
    transcript = await client.transcribe(_silence(), filename="call.mp3", language="uz")
    await client.aclose()
    rec.dump("Gemini - ASR - transcribe()")

    assert rec.request is not None
    assert "generativelanguage.googleapis.com" in str(rec.request.url)
    assert ":generateContent" in str(rec.request.url)
    # The registry default has to reach the URL
    assert "gemini-3.1-flash-lite" in str(rec.request.url)
    assert rec.request.headers["x-goog-api-key"] == FAKE_KEY
    payload = json.loads(rec.body)
    parts = payload["contents"][0]["parts"]
    assert any("inlineData" in part for part in parts), "the audio must be sent inline"
    assert transcript.text == "OK"
    assert transcript.provider == "gemini"
    assert transcript.model == "gemini-3.1-flash-lite"
    assert transcript.language == "uz"


@pytest.mark.asyncio
async def test_gemini_asr_sends_the_audio_verbatim(configured_key: str) -> None:
    """The bytes handed to the provider are the bytes that came off the stream.

    An encoding bug here is invisible in the transcript — it comes back as a
    plausible transcript of nothing.
    """
    import base64

    rec = Recorder(GEMINI_JSON)
    client = _client("gemini", ROLE_ASR, rec)
    await client.transcribe(_silence(), filename="call.mp3", language=None)
    await client.aclose()
    payload = json.loads(rec.body)
    inline = next(p["inlineData"] for p in payload["contents"][0]["parts"] if "inlineData" in p)
    assert base64.b64decode(inline["data"]) == b"\x00" * 32
    assert inline["mimeType"] == "audio/mpeg"


@pytest.mark.asyncio
async def test_gemini_llm_request_shape_and_schema(configured_key: str) -> None:
    rec = Recorder(GEMINI_JSON)
    client = _client("gemini", ROLE_LLM, rec)
    answer = await client.complete(
        system="You score the call.",
        user="Transcript: ...",
        schema={"type": "object", "properties": {"score": {"type": "integer"}}},
        max_tokens=2048,
    )
    await client.aclose()
    rec.dump("Gemini - LLM - complete()")

    assert rec.request is not None
    assert "gemini-3.1-flash-lite" in str(rec.request.url)
    payload = json.loads(rec.body)
    config = payload["generationConfig"]
    assert config["maxOutputTokens"] == 2048
    assert config["responseMimeType"] == "application/json"
    instruction = payload["systemInstruction"]["parts"][0]["text"]
    assert instruction.startswith("You score the call.")
    # The schema rides in the system instruction rather than in a vendor field,
    # which is what keeps this working across SDK versions
    assert json.loads(instruction.split("\n")[-1]) == {
        "properties": {"score": {"type": "integer"}},
        "type": "object",
    }
    assert answer == "OK"


@pytest.mark.asyncio
async def test_gemini_llm_without_a_schema_asks_for_plain_text(configured_key: str) -> None:
    rec = Recorder(GEMINI_JSON)
    client = _client("gemini", ROLE_LLM, rec)
    await client.complete(system="system", user="user", max_tokens=64)
    await client.aclose()
    config = json.loads(rec.body)["generationConfig"]
    assert "responseMimeType" not in config


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ROLE_ASR, ROLE_LLM])
async def test_ping_sends_a_real_request(role: str, configured_key: str) -> None:
    """The configuration check has to be a real call, or it checks nothing."""
    rec = Recorder(GEMINI_JSON)
    client = _client("gemini", role, rec)
    answer = await client.ping()
    await client.aclose()
    assert rec.request is not None, "ping must send a real request"
    assert answer
    print(f"   ping gemini/{role} -> {rec.request.method} {rec.request.url}")


@pytest.mark.asyncio
async def test_one_sdk_client_per_provider_client_and_it_can_be_closed(
    configured_key: str,
) -> None:
    """The SDK holds a connection pool; two calls must not hold two.

    ``google-genai`` builds an ``httpx.AsyncClient`` inside every
    ``genai.Client`` and only closes it from a finaliser, which by then has no
    loop to run on. One transcription used to build two of them.
    """
    rec = Recorder(GEMINI_JSON)
    client = _client("gemini", ROLE_ASR, rec)
    await client.transcribe(_silence(), filename="a.mp3", language=None)
    first = client._sdk
    await client.transcribe(_silence(), filename="b.mp3", language=None)
    assert client._sdk is first, "a second call must reuse the SDK client"

    await client.aclose()
    assert client._sdk is None
    await client.aclose()  # closing twice is not an error


# --- 4. Vendor errors become named, redacted failures -----------------------


def test_auth_failure_is_detected_even_when_the_vendor_returns_400() -> None:
    """Gemini answers an invalid key with 400, not 401 — found in live testing."""

    class VendorError(Exception):
        code = 400
        message = "API key not valid. Please pass a valid API key."

    error = translate(
        VendorError(), provider_label="Google Gemini", model="gemini-3.1-flash-lite"
    )
    assert error.code == AnalysisFailure.PROVIDER_AUTH
    assert "wrong or revoked" in error.message


def test_the_vendor_text_is_withheld_on_an_auth_failure() -> None:
    """Some providers echo part of the key back in a 401 body."""

    class VendorError(Exception):
        status_code = 401
        message = f"Incorrect API key provided: {FAKE_KEY}"

    error = translate(VendorError(), provider_label="Google Gemini", model="m")
    assert FAKE_KEY not in error.message
    assert "Incorrect API key provided" not in error.message


def test_a_daily_quota_is_not_the_same_event_as_a_minute_burst() -> None:
    """The distinction that left 858 calls permanently failed in BonviZvonki."""

    class Burst(Exception):
        status_code = 429
        message = "Rate limit reached. Please retry in 25.14s"

    class Daily(Exception):
        status_code = 429
        message = (
            "RESOURCE_EXHAUSTED: quota metric "
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier exceeded"
        )

    burst = translate(Burst(), provider_label="Google Gemini", model="m")
    assert burst.code == AnalysisFailure.PROVIDER_RATE_LIMIT
    assert burst.retry_after_sec == pytest.approx(25.14)
    assert burst.daily_quota is False

    daily = translate(Daily(), provider_label="Google Gemini", model="m")
    assert daily.daily_quota is True
    assert "until tomorrow" in daily.message


def test_a_5xx_is_unavailable_and_a_missing_sdk_is_its_own_failure() -> None:
    class ServerError(Exception):
        status_code = 503
        message = "backend overloaded"

    assert (
        translate(ServerError(), provider_label="Google Gemini", model="m").code
        == AnalysisFailure.PROVIDER_UNAVAILABLE
    )
    missing = translate(
        ModuleNotFoundError("No module named 'google'", name="google"),
        provider_label="Google Gemini",
        model="m",
    )
    assert missing.code == AnalysisFailure.SDK_MISSING
    assert "google" in missing.message


def test_a_network_failure_is_transient_not_a_vendor_rejection() -> None:
    error = translate(
        httpx.ConnectTimeout("timed out"), provider_label="Google Gemini", model="m"
    )
    assert error.code == AnalysisFailure.PROVIDER_NETWORK


def test_translate_never_re_wraps_one_of_ours() -> None:
    original = audio_too_large(MAX_AUDIO_MB)
    assert translate(original, provider_label="Google Gemini", model="m") is original
    assert original.code == AnalysisFailure.AUDIO_TOO_LARGE


def test_every_failure_code_is_a_storable_analysis_failure() -> None:
    """``failure_code`` is a PostgreSQL enum: a code outside it is a write error.

    Walking the subclasses rather than listing them, so a failure added later
    cannot skip this.
    """
    seen: list[type[ProviderError]] = []
    pending = [ProviderError]
    while pending:
        cls = pending.pop()
        seen.append(cls)
        pending.extend(cls.__subclasses__())
    assert len(seen) >= 9
    for cls in seen:
        assert cls.code in set(AnalysisFailure), f"{cls.__name__}.code={cls.code!r}"


# --- 5. A key never reaches a log line (N26) --------------------------------


def test_redact_removes_configured_and_pattern_secrets() -> None:
    text = f"Incorrect API key provided: {FAKE_KEY}. Also gsk_ABCDEFGHIJKLMNOP123456"
    cleaned = redact(text, (FAKE_KEY,))
    assert FAKE_KEY not in cleaned
    assert "gsk_ABCDEFGHIJKLMNOP123456" not in cleaned
    assert REDACTED in cleaned


def test_redact_uses_the_configured_key_without_being_told(configured_key: str) -> None:
    """The call site does not have to remember to pass the key.

    This is the branch that matters: an error path nobody reviewed logs the
    vendor's text with no ``secrets`` argument, and the key must still not be
    in it.
    """
    cleaned = redact(f"upstream said: {FAKE_KEY} is revoked")
    assert FAKE_KEY not in cleaned
    assert REDACTED in cleaned


def test_a_google_api_key_shape_is_redacted_even_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shape Google issues, caught by pattern rather than by exact match.

    The interesting case is a key that is NOT ours — a second project's key
    echoed back by the vendor is still a secret in a log line.
    """
    monkeypatch.setattr(get_settings(), "ai_gemini_api_key", SecretStr(""))
    leaked = "AIzaSyD-0123456789abcdefghijklmnopqrstu"
    assert leaked not in redact(f"401 from vendor: key={leaked}")


# --- 6. The audio guard -----------------------------------------------------


@pytest.mark.asyncio
async def test_collect_audio_refuses_more_than_the_ceiling() -> None:
    async def flood():
        for _ in range(3):
            yield b"\x00" * (1024 * 1024)

    with pytest.raises(ProviderError) as excinfo:
        await collect_audio(flood(), limit_mb=2)
    assert excinfo.value.code == AnalysisFailure.AUDIO_TOO_LARGE


@pytest.mark.asyncio
async def test_collect_audio_never_touches_the_disk(tmp_path) -> None:
    """The stream is gathered in memory; the recording has exactly one home."""
    before = set(tmp_path.iterdir())
    assert await collect_audio(_silence()) == b"\x00" * 32
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("call.mp3", "audio/mpeg"),
        ("call.M4A", "audio/mp4"),
        ("call.wav", "audio/wav"),
        ("call.opus", "audio/ogg"),
        ("call", "audio/mpeg"),
    ],
)
def test_guess_mime_covers_the_containers_this_product_stores(
    filename: str, mime: str
) -> None:
    assert guess_mime(filename) == mime


# --- 7. The SDK import is lazy ----------------------------------------------


def test_importing_the_factory_imports_no_vendor_sdk() -> None:
    """A missing package must be an error at call time, not a dead server.

    Asserted by reading the source rather than by uninstalling: a top-level
    ``import google`` in a client is exactly the edit this forbids, and it
    would otherwise only show up on a machine where the package is absent.
    """
    from pathlib import Path

    providers = Path(__file__).resolve().parents[1] / "providers"
    offenders: list[str] = []
    for path in sorted(providers.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            if line.startswith((" ", "\t")):  # inside a function — that is the point
                continue
            if any(
                stripped.startswith(prefix)
                for prefix in ("import google", "from google", "import openai", "from openai")
            ):
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert offenders == [], (
        "a vendor SDK is imported at module level:\n  " + "\n  ".join(offenders)
    )
