"""Reference-data wire schemas (SPEC §3.8, §4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import AppVariant, DirectoryRuleKind, InstallationStatus
from src.core.wire import Int64


class CreateDirectoryEntryRequest(BaseModel):
    """``POST /api/v1/line-directory`` — an admin extra for UC-25."""

    pattern: str = Field(
        min_length=2,
        max_length=32,
        description="Digits to match. UC-25's '*700' is the suffix rule '700'.",
    )
    kind: DirectoryRuleKind
    label: str | None = Field(default=None, max_length=64)


class DirectoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pattern: str
    kind: DirectoryRuleKind
    label: str | None
    is_active: bool
    created_at: datetime


class DirectoryEntryListResponse(BaseModel):
    items: list[DirectoryEntryResponse]
    total: int


class ReclassifyResponse(BaseModel):
    """A directory change is only half done until the calls agree with it."""

    entry: DirectoryEntryResponse
    calls_reclassified: int = Field(
        description="Calls whose call_type changed as a result of this edit."
    )


class UploadReleaseRequest(BaseModel):
    """The metadata beside an uploaded APK (T58, N33).

    The version code is supplied rather than read out of the file: extracting
    it means decoding a binary ``AndroidManifest.xml``, and a wrong code is
    caught by the unique constraint and by phones not seeing an update. The
    *signature* is the opposite — nothing catches a wrong key until fifteen
    people cannot install the build — so that is read from the bytes and never
    accepted from the uploader.
    """

    version: str = Field(max_length=20, description="Human version, e.g. '1.4.0'.")
    version_code: int = Field(ge=1, description="What the version gate compares (N34).")
    variant: AppVariant
    min_api_level: int = Field(default=26, ge=21, le=40, description="N32's floor.")
    release_notes_uz: str | None = Field(default=None, max_length=4000)
    is_mandatory: bool = Field(
        default=False, description="Drives `update.required` in every response."
    )


class AppVersionResponse(BaseModel):
    """One build in the distribution record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    version_code: int
    variant: AppVariant
    apk_sha256: str = Field(description="Computed server-side, never accepted.")
    size_bytes: Int64
    min_api_level: int
    release_notes_uz: str | None
    is_mandatory: bool
    is_current: bool
    published_at: datetime | None = Field(
        description="NULL means uploaded but not published — reaches nobody."
    )
    created_at: datetime
    created_by: uuid.UUID | None
    created_by_name: str = Field(
        default="",
        description=(
            "Who uploaded it, resolved server-side. The id alone would make "
            "every page re-solve it through `GET /users`, which a manager "
            "cannot read — so a manager would see a bare uuid."
        ),
    )

    @property
    def download_path(self) -> str:
        return f"/api/v1/app/download/{self.version_code}"


class AppVersionListResponse(BaseModel):
    items: list[AppVersionResponse]
    total: int
    signing_sha256_configured: bool = Field(
        description=(
            "Whether a signing fingerprint is configured. False means uploads "
            "are accepted without the key check — see docs/APK-SIGNING.md."
        )
    )


class UploadReleaseResponse(BaseModel):
    """What the upload found in the file, alongside the row it created."""

    version: AppVersionResponse
    signer_sha256: str = Field(
        description=(
            "SHA-256 of the signing certificate, read from the APK's v2/v3 "
            "signing block. Compare it against docs/APK-SIGNING.md by eye if "
            "no fingerprint is configured yet — a build signed by another key "
            "cannot be installed as an update, only as an uninstall that "
            "destroys the phone's unsent queue."
        )
    )
    signer_verified: bool = Field(
        description="True when it was checked against the configured fingerprint."
    )


class StrandedInstallationOut(BaseModel):
    """One phone a proposed minimum version would refuse."""

    installation_id: uuid.UUID
    agent_name: str
    device: str
    app_version: str | None
    app_version_code: int | None
    status: InstallationStatus
    last_heartbeat_at: datetime | None


class VersionGateImpactResponse(BaseModel):
    """What raising the floor would cost, **before** it is raised (N34, UC-28).

    These are personally owned handsets. A stranded phone drains its queue,
    is then refused, and stays refused until somebody physically reaches that
    salesperson — so this is not a preview of a config change, it is the cost
    of a decision, and the panel shows it before the button.
    """

    version_code: int = Field(description="The minimum being considered.")
    current_min_version_code: int
    stranded_count: int
    stranded: list[StrandedInstallationOut]
    unknown_version_count: int = Field(
        description=(
            "Active phones that have never reported a version code. The gate "
            "lets these through, so they are not counted as stranded — but "
            "each one might be below the floor and we cannot say."
        )
    )


class SetMinimumVersionRequest(BaseModel):
    """``PUT /api/v1/app/min-version``.

    ``acknowledged_stranded`` must equal the count the impact endpoint returns
    right now. Not ceremony: it fails exactly when the number moved between
    looking and deciding, which is when the admin's picture is stale.
    """

    version_code: int = Field(ge=1)
    acknowledged_stranded: int = Field(
        ge=0, description="The stranded count you just saw. Must still be true."
    )


class SetMinimumVersionResponse(BaseModel):
    version_code: int
    stranded_count: int
