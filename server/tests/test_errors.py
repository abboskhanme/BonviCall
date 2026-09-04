"""The error envelope, and the codes that are wire contract (N35, §9)."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from src.core.errors import (
    AppError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    GoneError,
    MethodNotAllowedError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    UnauthorizedError,
    ValidationError,
    VersionUnsupportedError,
)
from src.core.messages_uz import DEVICE_PROTOCOL_CODES, MESSAGES, message_for
from src.main import create_app


class _Body(BaseModel):
    count: int


def _app_with_failing_routes():
    """An app whose only routes fail, one per handler."""
    app = create_app()
    router = APIRouter(prefix="/_probe")

    @router.get("/app-error")
    async def _app_error() -> None:
        raise ConflictError(ErrorCode.NUMBER_ALREADY_ASSIGNED, detail={"holder": "Aziz"})

    @router.get("/rate-limited")
    async def _rate_limited() -> None:
        raise RateLimitedError(retry_after_sec=30)

    @router.post("/validation")
    async def _validation(body: _Body) -> dict:
        return {"count": body.count}

    @router.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("a token: secret-abcd1234")

    app.include_router(router)
    return app


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


def test_every_status_code_is_the_one_the_spec_names() -> None:
    """SPEC §4.0's status table, pinned. A silent change here breaks a client."""
    expected = {
        UnauthorizedError: 401,
        ForbiddenError: 403,
        NotFoundError: 404,
        MethodNotAllowedError: 405,
        ConflictError: 409,
        GoneError: 410,
        PayloadTooLargeError: 413,
        ValidationError: 422,
        VersionUnsupportedError: 426,
        RateLimitedError: 429,
    }
    for error_class, status in expected.items():
        assert error_class.status_code == status, error_class.__name__


def test_codes_are_snake_case_and_unique() -> None:
    """``code`` is machine contract: snake_case, stable forever (§9)."""
    codes = sorted(ErrorCode.all_codes())
    assert len(codes) == len(set(codes))
    for code in codes:
        assert code == code.lower()
        assert code.replace("_", "").isalnum(), code


def test_every_code_has_a_message() -> None:
    """A code with no catalogue entry would reach a user as the fallback."""
    missing = sorted(ErrorCode.all_codes() - set(MESSAGES))
    assert missing == [], f"no message for: {missing}"


def test_user_facing_messages_are_not_english_placeholders() -> None:
    """Every message a person reads is Uzbek (§14); device-protocol codes are not."""
    for code, message in MESSAGES.items():
        if code in DEVICE_PROTOCOL_CODES:
            continue
        assert message, code
        assert not message.startswith("A "), code


def test_message_for_falls_back_rather_than_raising() -> None:
    assert message_for("a_code_that_does_not_exist")


def test_app_error_takes_the_class_code_by_default() -> None:
    assert AppError().code == ErrorCode.APP_ERROR
    assert NotFoundError().code == ErrorCode.NOT_FOUND
    assert NotFoundError(ErrorCode.CALL_NOT_FOUND).code == ErrorCode.CALL_NOT_FOUND


@pytest.mark.asyncio
async def test_app_error_renders_the_envelope() -> None:
    async with _client(_app_with_failing_routes()) as client:
        response = await client.get("/_probe/app-error")
    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == ErrorCode.NUMBER_ALREADY_ASSIGNED
    assert body["error"]["message"] == message_for(ErrorCode.NUMBER_ALREADY_ASSIGNED)
    assert body["error"]["detail"] == {"holder": "Aziz"}
    assert body["error"]["request_id"]


@pytest.mark.asyncio
async def test_rate_limited_carries_retry_after() -> None:
    async with _client(_app_with_failing_routes()) as client:
        response = await client.get("/_probe/rate-limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.json()["error"]["code"] == ErrorCode.RATE_LIMITED


@pytest.mark.asyncio
async def test_validation_error_uses_the_same_envelope() -> None:
    """Pydantic failures arrive as ``validation_error``, not FastAPI's shape."""
    async with _client(_app_with_failing_routes()) as client:
        response = await client.post("/_probe/validation", json={"count": "not a number"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert body["error"]["detail"]["fields"][0]["field"].endswith("count")


@pytest.mark.asyncio
async def test_unhandled_exception_keeps_the_envelope_and_leaks_nothing() -> None:
    """The reason the third handler exists: the Android queue parses one shape.

    A 500 rendered as FastAPI's ``{"detail": ...}`` is indistinguishable from a
    corrupted body, and the client cannot then decide whether to retry.
    """
    async with _client(_app_with_failing_routes()) as client:
        response = await client.get("/_probe/boom")
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == ErrorCode.INTERNAL_ERROR
    assert "detail" not in body["error"]
    assert "RuntimeError" not in response.text
    assert "secret-abcd1234" not in response.text


@pytest.mark.asyncio
async def test_an_unrouted_path_still_carries_the_envelope() -> None:
    """Starlette answers this one before any of our routes exist.

    Without a handler for it the client gets ``{"detail": "Not Found"}`` — a
    second body shape, which is the whole failure §9 is about.
    """
    async with _client(_app_with_failing_routes()) as client:
        response = await client.get("/api/v1/definitely-not-a-route")
    assert response.status_code == 404
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == ErrorCode.NOT_FOUND
    assert response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_wrong_method_still_carries_the_envelope() -> None:
    async with _client(_app_with_failing_routes()) as client:
        response = await client.post("/_probe/app-error")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_ALLOWED


@pytest.mark.asyncio
async def test_request_id_is_echoed_when_the_client_supplies_one() -> None:
    async with _client(_app_with_failing_routes()) as client:
        response = await client.get(
            "/_probe/app-error", headers={"X-Request-Id": "abc-123"}
        )
    assert response.headers["X-Request-Id"] == "abc-123"
    assert response.json()["error"]["request_id"] == "abc-123"
