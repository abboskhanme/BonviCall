"""The self-hosted update channel (T58, N33, N34, UC-28).

The APK is not on Google Play — Play policy prohibits call-recording apps — so
this server is the update channel and this table is the distribution record.

Two of these endpoints are dangerous and the shapes reflect it:

* **``PUT /min-version`` strands phones.** Raising the floor means every
  handset below it drains its queue and is then refused, and these are
  personally owned phones: a refused one stops reporting until somebody
  physically reaches that salesperson. So ``GET /min-version/impact`` exists to
  be read *first*, and the change has to name the number it saw.
* **``POST /versions`` accepts a binary that phones will install.** The
  SHA-256 and the size are computed here, never accepted, and the signing
  certificate is read out of the file. A build signed by the wrong key cannot
  be installed as an update at all — only as an uninstall-and-reinstall, which
  destroys every unsent call on the handset — so that is a refusal.

``GET /download/{version_code}`` is public (SPEC §4.1 rule 5): the install
landing page redirects a salesperson's browser here and there is no session to
authenticate. It serves published builds only, is rate-limited like the landing
page, and answers 404 for an unpublished build rather than 403 — "that build
exists but you may not have it" is information a stranger has no reason to get.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from src.core import ratelimit
from src.core.config import get_settings
from src.core.deps import PrincipalDep, SessionDep
from src.core.enums import AppVariant
from src.core.errors import ErrorCode, PayloadTooLargeError
from src.core.permissions import Perm, require_permission
from src.modules.catalog.rules import normalise_fingerprint
from src.modules.catalog.schemas import (
    AppVersionListResponse,
    AppVersionResponse,
    SetMinimumVersionRequest,
    SetMinimumVersionResponse,
    StrandedInstallationOut,
    UploadReleaseRequest,
    UploadReleaseResponse,
    VersionGateImpactResponse,
)
from src.modules.catalog.service import ReleaseService
from src.modules.installations.service import (
    SETTING_MIN_VERSION_CODE,
    VersionGateService,
)
from src.modules.settings.service import SettingsService

router = APIRouter(prefix="/app", tags=["App versions"])

#: An APK is tens of megabytes; anything an order of magnitude larger is not
#: one, and the ceiling exists so a mistaken upload is refused before it is
#: read into memory rather than after.
MAX_APK_BYTES = 200 * 1024 * 1024

#: Streamed in chunks, so a 30 MB download does not become a 30 MB string.
DOWNLOAD_CHUNK_BYTES = 64 * 1024


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get(
    "/versions",
    response_model=AppVersionListResponse,
    dependencies=[Depends(require_permission(Perm.APPVERSIONS_READ))],
)
async def list_versions(session: SessionDep) -> AppVersionListResponse:
    """Every build, newest first. Both variants — they ship in lockstep."""
    rows, total = await ReleaseService(session).list_versions()
    return AppVersionListResponse(
        items=[AppVersionResponse.model_validate(row) for row in rows],
        total=total,
        signing_sha256_configured=bool(
            normalise_fingerprint(get_settings().apk_signing_sha256)
        ),
    )


@router.post(
    "/versions",
    response_model=UploadReleaseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.APPVERSIONS_WRITE))],
)
async def upload_version(
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
    apk: Annotated[UploadFile, File(description="The signed APK.")],
    version: Annotated[str, Form()],
    version_code: Annotated[int, Form()],
    variant: Annotated[AppVariant, Form()],
    min_api_level: Annotated[int, Form()] = 26,
    release_notes_uz: Annotated[str | None, Form()] = None,
    is_mandatory: Annotated[bool, Form()] = False,
) -> UploadReleaseResponse:
    """Store a build. **Uploaded is not published** — this reaches nobody yet.

    ``multipart/form-data`` rather than the JSON everything else uses, because
    the payload is a binary the admin picked in a file dialog. It is the only
    such endpoint in the product.
    """
    payload = await apk.read()
    if len(payload) > MAX_APK_BYTES:
        raise PayloadTooLargeError(
            ErrorCode.PAYLOAD_TOO_LARGE, detail={"max_bytes": MAX_APK_BYTES}
        )

    meta = UploadReleaseRequest(
        version=version,
        version_code=version_code,
        variant=variant,
        min_api_level=min_api_level,
        release_notes_uz=release_notes_uz,
        is_mandatory=is_mandatory,
    )
    row, inspection = await ReleaseService(session).upload(
        payload, meta, principal.id, _client_ip(request)
    )
    return UploadReleaseResponse(
        version=AppVersionResponse.model_validate(row),
        signer_sha256=inspection.signer_sha256,
        signer_verified=bool(normalise_fingerprint(get_settings().apk_signing_sha256)),
    )


@router.post(
    "/versions/{version_id}/publish",
    response_model=AppVersionResponse,
    dependencies=[Depends(require_permission(Perm.APPVERSIONS_WRITE))],
)
async def publish_version(
    version_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> AppVersionResponse:
    """Make it current for its variant. Every phone is offered it from now on."""
    row = await ReleaseService(session).publish(
        version_id, principal.id, _client_ip(request)
    )
    return AppVersionResponse.model_validate(row)


@router.get(
    "/min-version/impact",
    response_model=VersionGateImpactResponse,
    dependencies=[Depends(require_permission(Perm.APPVERSIONS_READ))],
)
async def min_version_impact(
    version_code: int, session: SessionDep
) -> VersionGateImpactResponse:
    """Who a proposed minimum would strand — read this before changing it.

    Deliberately a ``GET`` with the candidate in the query string, so it can be
    called repeatedly while an admin tries numbers, and so the panel can show
    the cost live beside the input rather than after the fact.
    """
    gate = VersionGateService(session)
    stranded_count, stranded = await gate.impact_of(version_code)
    return VersionGateImpactResponse(
        version_code=version_code,
        current_min_version_code=await SettingsService(session).get_int(
            SETTING_MIN_VERSION_CODE
        ),
        stranded_count=stranded_count,
        stranded=[
            StrandedInstallationOut(
                installation_id=row.installation_id,
                agent_name=row.agent_name,
                device=row.device,
                app_version=row.app_version,
                app_version_code=row.app_version_code,
                status=row.status,
                last_heartbeat_at=row.last_heartbeat_at,
            )
            for row in stranded
        ],
        unknown_version_count=await gate.unknown_version_count(),
    )


@router.put(
    "/min-version",
    response_model=SetMinimumVersionResponse,
    dependencies=[Depends(require_permission(Perm.APPVERSIONS_WRITE))],
)
async def set_min_version(
    payload: SetMinimumVersionRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> SetMinimumVersionResponse:
    """Raise or lower the floor, having stated what it costs.

    409 ``stranded_count_mismatch`` when the number moved since the impact was
    read. That is not pedantry — it is the case where the admin is deciding
    against a picture that is no longer true.
    """
    stranded = await VersionGateService(session).set_minimum(
        payload.version_code,
        payload.acknowledged_stranded,
        principal.id,
        _client_ip(request),
    )
    return SetMinimumVersionResponse(
        version_code=payload.version_code, stranded_count=stranded
    )


@router.get("/download/{version_code}")
async def download_version(version_code: int, request: Request, session: SessionDep):
    """The APK itself. **Public** (SPEC §4.1 rule 5), rate-limited.

    The install landing page sends a salesperson's browser here and that
    browser has no session. The binary is a client and holds no secret; the
    enrolment code is the secret, and it guards the page that links here.
    """
    ratelimit.hit("apk_download", _client_ip(request), ratelimit.APK_DOWNLOAD_PER_IP)
    row, handle = await ReleaseService(session).open_download(version_code)

    def _stream():
        with handle:
            while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
                yield chunk

    return StreamingResponse(
        _stream(),
        media_type="application/vnd.android.package-archive",
        headers={
            "Content-Length": str(row.size_bytes),
            "Content-Disposition": (
                f'attachment; filename="bonvicall-{row.variant.value}-'
                f'{row.version_code}.apk"'
            ),
            # The phone can verify it got the bytes we recorded. Cheap, and the
            # only integrity check available on a self-hosted channel.
            "X-Apk-Sha256": row.apk_sha256,
        },
    )
