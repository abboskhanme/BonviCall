"""``GET /i/{code}`` — the install landing page (UC-02, SPEC §8.1).

It belongs to no API surface: its audience is one salesperson with a phone, and
its content type is HTML. Public, because the code in the URL is the only secret
there is — single-use, 24 hours, and revocable.

Rate-limited because it is public and because the APK route behind it serves a
binary. The limit is per source address and is documented in
``core/ratelimit.py`` as the per-process approximation it is.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.core import ratelimit
from src.core.deps import SessionDep
from src.modules.enrolment.landing import (
    render_apk_missing,
    render_invitation,
    render_unavailable,
)
from src.modules.enrolment.service import EnrolmentService

router = APIRouter(tags=["Install"], include_in_schema=False)

#: Where the published build is served from (SPEC §8.1 step 3). Built by the
#: app-versions task; the landing page redirects to it rather than streaming
#: the bytes itself, so the funnel signal is one row and the file is served
#: once, from one place.
APK_PATH = "/api/v1/app/download/{version_code}"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _public_origin(request: Request) -> str:
    """The address this page was reached on, as the phone would have to type it.

    It goes into the deep link as ``&server=``, and that parameter is the ONLY
    way a release build can be pointed at a server — a typed address is refused
    there on purpose (``ServerAddress``), because a field that repoints a
    salesperson's handset would send every call they make somewhere else.

    Read from the forwarded headers first: behind Caddy the app server sees
    plain HTTP on an internal name, and handing the phone ``http://backend:8000``
    is an address that resolves nowhere and, being cleartext, is refused by the
    client's own network config before it is even tried.
    """
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("Host") or request.url.netloc
    return f"{scheme}://{host}"


@router.get("/i/{code}", response_class=HTMLResponse)
async def install_page(code: str, request: Request, session: SessionDep) -> HTMLResponse:
    """The agent-facing install page. Works with JavaScript off."""
    ratelimit.hit("install_page", _client_ip(request), ratelimit.INSTALL_PAGE_PER_IP)
    context = await EnrolmentService(session).invitation_for(code)
    if context is None:
        return HTMLResponse(render_unavailable(), status_code=404)
    agent_name, number_e164, normalised_code, version_code = context
    return HTMLResponse(
        render_invitation(
            agent_name=agent_name,
            number_e164=number_e164,
            code=normalised_code,
            user_agent=request.headers.get("User-Agent"),
            apk_available=version_code is not None,
            server_base=_public_origin(request),
        )
    )


@router.get("/i/{code}/apk")
async def install_apk(code: str, request: Request, session: SessionDep):
    """Hand over the build. Per-agent link, so the panel can see who downloaded.

    That download is the first funnel signal after ``invited``, which is why
    this indirection exists instead of linking the file directly.
    """
    ratelimit.hit("install_apk", _client_ip(request), ratelimit.APK_DOWNLOAD_PER_IP)
    context = await EnrolmentService(session).invitation_for(code)
    if context is None:
        return HTMLResponse(render_unavailable(), status_code=404)
    version_code = context[3]
    if version_code is None:
        return HTMLResponse(render_apk_missing(), status_code=404)
    return RedirectResponse(APK_PATH.format(version_code=version_code), status_code=302)
