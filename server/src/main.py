"""The FastAPI application: error envelope, request id, routers (T16).

Routers are registered here and nowhere else. Modules create routers; this file
mounts them.

**Four exception handlers.** CONVENTIONS.md §9 names three — ``AppError``,
``RequestValidationError`` and a generic ``Exception`` — and the rule it states
is stronger than the count: *every* non-2xx response carries the envelope,
including 500. Three handlers do not achieve that. Starlette answers an
unrouted path with ``{"detail": "Not Found"}`` and a wrong method with
``{"detail": "Method Not Allowed"}`` before any of our handlers is reached, so
``StarletteHTTPException`` is handled too. It was verified by ``curl``, not
assumed.

Why the rule matters: BonviZvonki has no generic handler, so an unhandled 500
there returns FastAPI's ``{"detail": "Internal Server Error"}``. The Android
client parses exactly one envelope shape — a response that does not match it is
indistinguishable from a corrupted body, and the upload queue then cannot decide
whether to retry, which loses calls or duplicates them. The traceback is logged
with the request id and **never** sent to the client.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Imported to *handle*, never to raise. CONVENTIONS.md §15 forbids raising an
# HTTPException; Starlette raises its own for an unknown path or a wrong method
# before our code runs, and catching it is what keeps the envelope universal.
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api import device, panel, service
from src.api import health as health_api
from src.api import install as install_api

# Importing the registry is what guarantees every mapper is known before any
# ForeignKey string is resolved (CONVENTIONS.md §10). Do not remove it because
# "nothing in this file uses it" — that is exactly the failure it prevents.
from src.core import models as _model_registry  # noqa: F401
from src.core.config import get_settings
from src.core.deps import REQUEST_ID_HEADER, get_principal_resolver, set_principal_resolver
from src.core.errors import AppError, ErrorCode, RateLimitedError
from src.core.logging import configure_logging, get_logger
from src.core.messages_uz import message_for
from src.modules.auth.service import resolve_principal

log = get_logger(__name__)

API_TITLE = "BonviCall"
API_VERSION = "1.0.0"
API_DESCRIPTION = (
    "Call capture for Bonvi's SIM fleet. Three surfaces: /api/device/v1 (the "
    "Android app), /api/v1 (the panel), /api/service/v1 (machine export)."
)


def error_envelope(
    code: str,
    request_id: str,
    message: str | None = None,
    detail: Any = None,
) -> dict[str, dict[str, Any]]:
    """The one response shape for every non-2xx answer (N35, SPEC §4.0)."""
    body: dict[str, Any] = {
        "code": code,
        "message": message or message_for(code),
        "request_id": request_id,
    }
    if detail is not None:
        body["detail"] = detail
    return {"error": body}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Anything a router or service raised deliberately."""
    log.info(
        "app_error",
        error_code=exc.code,
        status=exc.status_code,
        path=request.url.path,
    )
    headers = {}
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after_sec)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(exc.code, _request_id(request), exc.message, exc.detail),
        headers=headers,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic's field-shape failures, in our envelope rather than FastAPI's.

    ``detail`` carries the field list so the panel can point at the input; the
    Android client branches on ``code`` alone and ignores it.
    """
    fields = [
        {
            "field": ".".join(str(part) for part in err.get("loc", ())),
            "reason": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    log.info("validation_error", path=request.url.path, fields=fields)
    return JSONResponse(
        status_code=422,
        content=error_envelope(
            ErrorCode.VALIDATION_ERROR, _request_id(request), detail={"fields": fields}
        ),
    )


#: Starlette's own failures, mapped onto our stable codes. Anything not listed
#: becomes ``bad_request`` (4xx) or ``internal_error`` (5xx).
FRAMEWORK_STATUS_CODES: dict[int, str] = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


async def framework_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Routing failures — an unknown path, a wrong method — in our envelope.

    These never reach the ``AppError`` handler because Starlette raises them
    before the route function exists, which is precisely why a client hitting a
    typo in a URL used to get a body it could not parse.
    """
    code = FRAMEWORK_STATUS_CODES.get(
        exc.status_code,
        ErrorCode.BAD_REQUEST if exc.status_code < 500 else ErrorCode.INTERNAL_ERROR,
    )
    log.info("framework_error", error_code=code, status=exc.status_code, path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(code, _request_id(request)),
        headers=getattr(exc, "headers", None),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything we did not foresee. The envelope holds; the traceback does not leave.

    Broad on purpose, and this is the one place in the server where that is
    correct: the alternative is FastAPI's own body shape, which the Android
    client cannot parse.
    """
    log.exception(
        "unhandled_error",
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=error_envelope(ErrorCode.INTERNAL_ERROR, _request_id(request)),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up checks that should fail loudly rather than at the first request."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)
    settings.assert_production_ready()
    if get_principal_resolver() is None:
        # Truthful, and loud: without an authenticating module registered,
        # every protected route answers 401.
        log.warning(
            "no_principal_resolver_registered",
            consequence="every authenticated route will answer 401 unauthorized",
        )
    log.info("startup", environment=settings.environment, version=API_VERSION)
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    """Build the application. Used by uvicorn, by the tests and by the contract export."""
    settings = get_settings()
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Give every request an id, echo it, and bind it to the log context."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, framework_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    # The one piece of wiring core cannot do for itself: core/ must not import
    # a module, so the composition root hands the authenticating function to
    # core/deps at build time (CONVENTIONS.md §11 item 1).
    set_principal_resolver(resolve_principal)

    app.include_router(health_api.router)
    app.include_router(install_api.router)
    app.include_router(device.router)
    app.include_router(panel.router)
    app.include_router(service.router)
    return app


app = create_app()
