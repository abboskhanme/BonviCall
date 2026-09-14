"""The self-hosted update channel (T58, N33, N34, UC-28).

The APKs here are **synthetic**: a zip with an ``AndroidManifest.xml`` and a
hand-built APK Signing Block, a few hundred bytes each. The real debug build is
12 MB and putting it through every test would trade a minute of suite time for
nothing — the parser is exercised against the real thing in
``test_app_versions_rules.py``, which skips when the build is absent.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile

import pytest
import sqlalchemy as sa

from src.core import ratelimit
from src.modules.catalog.models import AppVersionModel

pytestmark = pytest.mark.asyncio

SCHEME_V2_ID = 0x7109_871A
CERTIFICATE = b"a certificate would be DER here, and the parser only hashes it"
SIGNER_SHA256 = hashlib.sha256(CERTIFICATE).hexdigest()


def _sized(payload: bytes) -> bytes:
    return struct.pack("<I", len(payload)) + payload


def signed_apk(certificate: bytes = CERTIFICATE, *, sign: bool = True) -> bytes:
    """A zip that looks enough like an APK for the publish path to judge it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary xml")
        archive.writestr("classes.dex", b"dex\n035\x00")
    payload = buffer.getvalue()
    if not sign:
        return payload

    # signers -> signer -> signed_data -> (digests, certificates -> cert)
    certificates = _sized(certificate)
    signed_data = _sized(b"digest") + _sized(certificates)
    signer = _sized(signed_data)
    signers = _sized(signer)
    value = _sized(signers)

    pair = struct.pack("<Q", 4 + len(value)) + struct.pack("<I", SCHEME_V2_ID) + value
    size = len(pair) + 8 + 16  # trailing size + magic
    block = struct.pack("<Q", size) + pair + struct.pack("<Q", size) + b"APK Sig Block 42"

    eocd = payload.rfind(b"PK\x05\x06")
    (cd_offset,) = struct.unpack_from("<I", payload, eocd + 16)
    patched = bytearray(payload[:cd_offset] + block + payload[cd_offset:])
    struct.pack_into("<I", patched, eocd + len(block) + 16, cd_offset + len(block))
    return bytes(patched)


def upload_form(version_code: int = 140, variant: str = "modern34") -> dict:
    return {
        "version": "1.4.0",
        "version_code": str(version_code),
        "variant": variant,
        "min_api_level": "26",
        "is_mandatory": "false",
    }


async def _upload(client, payload: bytes | None = None, **overrides):
    return await client.post(
        "/api/v1/app/versions",
        files={"apk": ("app.apk", payload or signed_apk(), "application/octet-stream")},
        data=upload_form(**overrides),
    )


# --- RBAC ------------------------------------------------------------------


async def test_listing_versions_needs_a_caller(client) -> None:
    assert (await client.get("/api/v1/app/versions")).status_code == 401


async def test_sales_cannot_read_or_publish_versions(sales) -> None:
    """A salesperson has no business in the distribution record."""
    assert (await sales.get("/api/v1/app/versions")).status_code == 403
    assert (await _upload(sales)).status_code == 403


async def test_a_manager_can_read_but_not_upload(manager) -> None:
    """`appversions:read` without `:write` — the split exists for this page."""
    assert (await manager.get("/api/v1/app/versions")).status_code == 200
    assert (await _upload(manager)).status_code == 403


# --- upload ----------------------------------------------------------------


async def test_a_file_that_is_not_an_apk_is_refused(admin) -> None:
    response = await _upload(admin, b"this is not a zip")
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"] == "not_a_zip"


async def test_a_zip_without_a_manifest_is_refused(admin) -> None:
    """Catches the wrong file in the file dialog, which is the common mistake."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"not an apk")
    response = await _upload(admin, buffer.getvalue())
    assert response.json()["error"]["detail"]["reason"] == "no_android_manifest"


async def test_an_unsigned_build_is_refused(admin) -> None:
    """A v1-only or unsigned build will not install on a modern target at all."""
    response = await _upload(admin, signed_apk(sign=False))
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"] == "no_v2_signature"


async def test_a_build_signed_by_the_wrong_key_is_refused(admin, monkeypatch) -> None:
    """The load-bearing one.

    Android will not install a differently-signed build as an update; the only
    route is uninstall-and-reinstall, which deletes every unsent call on the
    handset. On fifteen personal phones that is a data-loss event and a second
    visit to fifteen people, so it is a refusal and not a warning.
    """
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "apk_signing_sha256", "AA:BB:" + "cc" * 30)

    response = await _upload(admin)
    assert response.status_code == 422
    body = response.json()["error"]["detail"]
    assert body["reason"] == "signer_mismatch"
    assert body["found_sha256"] == SIGNER_SHA256


async def test_the_configured_fingerprint_is_compared_case_and_colon_insensitively(
    admin, monkeypatch
) -> None:
    """`keytool` prints colons, `apksigner` does not, and a person types one."""
    from src.core.config import get_settings

    colons = ":".join(SIGNER_SHA256[i : i + 2] for i in range(0, 64, 2)).upper()
    monkeypatch.setattr(get_settings(), "apk_signing_sha256", colons)

    response = await _upload(admin)
    assert response.status_code == 201, response.text
    assert response.json()["signer_verified"] is True


async def test_an_upload_is_stored_but_not_published(db, admin) -> None:
    """N33: uploaded is not published. This build reaches nobody yet."""
    payload = signed_apk()
    response = await _upload(admin, payload)
    assert response.status_code == 201

    body = response.json()
    assert body["signer_sha256"] == SIGNER_SHA256
    version = body["version"]
    # Computed here, never accepted from the uploader.
    assert version["apk_sha256"] == hashlib.sha256(payload).hexdigest()
    assert version["size_bytes"] == len(payload)
    assert version["published_at"] is None
    assert version["is_current"] is False


async def test_the_same_version_code_cannot_be_uploaded_twice(admin) -> None:
    """A version code is immutable once used, which is what makes the SHA mean
    anything — 'version 140' has to be one set of bytes."""
    assert (await _upload(admin)).status_code == 201
    clash = await _upload(admin)
    assert clash.status_code == 409
    assert clash.json()["error"]["detail"]["version_code"] == 140


async def test_the_same_code_may_exist_once_per_variant(admin) -> None:
    """`legacy28` and `modern34` ship in lockstep and share version codes."""
    assert (await _upload(admin, variant="modern34")).status_code == 201
    assert (await _upload(admin, variant="legacy28")).status_code == 201


# --- publish ---------------------------------------------------------------


async def test_publishing_makes_it_current_and_stands_down_the_previous(
    db, admin
) -> None:
    """One current build per variant, and the old bytes are kept.

    Deleting them would break a phone that is mid-download, and the row is the
    distribution record — "which build was current in March" has to stay
    answerable.
    """
    first = (await _upload(admin, version_code=140)).json()["version"]
    second = (await _upload(admin, version_code=141)).json()["version"]

    await admin.post(f"/api/v1/app/versions/{first['id']}/publish")
    published = await admin.post(f"/api/v1/app/versions/{second['id']}/publish")
    assert published.json()["is_current"] is True
    assert published.json()["published_at"] is not None

    current = await db.scalars(
        sa.select(AppVersionModel).where(AppVersionModel.is_current.is_(True))
    )
    rows = list(current.all())
    assert [row.version_code for row in rows] == [141]
    # The stood-down build still exists.
    assert await db.scalar(
        sa.select(sa.func.count()).select_from(AppVersionModel)
    ) == 2


# --- download --------------------------------------------------------------


async def test_the_download_is_public_and_serves_the_bytes(client, admin) -> None:
    """The install landing page sends a browser here with no session (§4.1)."""
    payload = signed_apk()
    version = (await _upload(admin, payload)).json()["version"]
    await admin.post(f"/api/v1/app/versions/{version['id']}/publish")

    response = await client.get("/api/v1/app/download/140")
    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/vnd.android.package-archive"
    assert response.headers["x-apk-sha256"] == hashlib.sha256(payload).hexdigest()
    assert "bonvicall-modern34-140.apk" in response.headers["content-disposition"]


async def test_an_unpublished_build_is_404_not_403(client, admin) -> None:
    """The endpoint is public, so "it exists but not for you" is information a
    stranger has no reason to receive."""
    await _upload(admin)
    assert (await client.get("/api/v1/app/download/140")).status_code == 404


async def test_a_version_that_does_not_exist_is_404(client) -> None:
    assert (await client.get("/api/v1/app/download/999")).status_code == 404


# --- the version gate: who gets stranded -----------------------------------


async def test_the_impact_names_the_phones_a_new_minimum_would_strand(
    admin, installation_factory
) -> None:
    """UC-28. The count comes before the change, because the change is a
    decision to make some salespeople stop reporting until someone reaches them.
    """
    behind = await installation_factory(app_version_code=139, app_version="1.3.9")
    await installation_factory(app_version_code=141, app_version="1.4.1")

    body = (await admin.get("/api/v1/app/min-version/impact?version_code=140")).json()
    assert body["stranded_count"] == 1
    assert [row["installation_id"] for row in body["stranded"]] == [str(behind.id)]
    # Enough to act on: who carries it and what it is.
    row = body["stranded"][0]
    assert row["agent_name"] and row["device"]
    assert row["app_version_code"] == 139


async def test_a_phone_of_unknown_version_is_not_counted_as_stranded(
    admin, installation_factory
) -> None:
    """It matches the gate, which fails open for a phone it cannot identify.

    Counting it would overstate the cost *and* name a phone that will in fact
    be let through — both of which make the number untrustworthy. It is
    reported separately as the honest uncertainty in the figure.
    """
    await installation_factory(app_version_code=None, app_version="1.3.9")

    body = (await admin.get("/api/v1/app/min-version/impact?version_code=140")).json()
    assert body["stranded_count"] == 0
    assert body["unknown_version_count"] == 1


async def test_a_revoked_phone_is_not_counted(admin, installation_factory) -> None:
    """It is already not reporting; listing it inflates the cost of the change."""
    from src.core.enums import InstallationStatus

    await installation_factory(
        app_version_code=100, status=InstallationStatus.REVOKED
    )
    body = (await admin.get("/api/v1/app/min-version/impact?version_code=140")).json()
    assert body["stranded_count"] == 0


async def test_raising_the_minimum_requires_the_number_you_saw(
    admin, installation_factory
) -> None:
    """409 when the count moved between looking and deciding.

    Not ceremony: that is exactly the case where the admin is acting on a
    picture that is no longer true — a phone enrolled a minute ago, or one that
    finally reported an old version.
    """
    await installation_factory(app_version_code=139)

    stale = await admin.put(
        "/api/v1/app/min-version",
        json={"version_code": 140, "acknowledged_stranded": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stranded_count_mismatch"
    assert stale.json()["error"]["detail"]["stranded_now"] == 1

    accepted = await admin.put(
        "/api/v1/app/min-version",
        json={"version_code": 140, "acknowledged_stranded": 1},
    )
    assert accepted.status_code == 200
    assert accepted.json()["stranded_count"] == 1


async def test_the_new_minimum_is_what_the_gate_then_uses(
    db, admin, installation_factory
) -> None:
    """The setting is not decoration — it has to reach the device path."""
    from src.modules.settings.service import SettingsService

    await admin.put(
        "/api/v1/app/min-version",
        json={"version_code": 140, "acknowledged_stranded": 0},
    )
    assert await SettingsService(db).get_int("app.min_supported_version_code") == 140


async def test_lowering_the_minimum_strands_nobody(admin, installation_factory) -> None:
    """The confirmation is free when the change is safe, which is the point."""
    await installation_factory(app_version_code=139)
    response = await admin.put(
        "/api/v1/app/min-version",
        json={"version_code": 1, "acknowledged_stranded": 0},
    )
    assert response.status_code == 200


async def test_sales_cannot_change_the_minimum(sales) -> None:
    response = await sales.put(
        "/api/v1/app/min-version",
        json={"version_code": 140, "acknowledged_stranded": 0},
    )
    assert response.status_code == 403


async def test_the_gate_compares_the_reported_code_not_the_version_string(
    db, installation_factory
) -> None:
    """The bug migration 003 exists for.

    With nowhere to store the reported code, the gate rebuilt one by
    concatenating the digits of the version *string*: "1.4.0" became 140 when
    the real code was 14. Both are integers and the comparison always succeeds,
    so nothing caught it — and the comparison decides which phones stop
    reporting.
    """
    from src.modules.installations.service import _version_code

    assert _version_code(14, "1.4.0", None) == 14, "the reported code wins"
    # And the fallback is still there for a row written before 003, still
    # failing open rather than refusing a client it cannot identify (N34).
    assert _version_code(None, "1.4.0", None) == 140
    assert _version_code(None, None, None) == 1


# --- discarding a mistake --------------------------------------------------


async def test_an_unpublished_build_can_be_taken_back(db, admin) -> None:
    """A mistyped version code would otherwise hold that code for ever."""
    version = (await _upload(admin, version_code=999)).json()["version"]
    assert (await admin.delete(f"/api/v1/app/versions/{version['id']}")).status_code == 204

    # And the code is free again, which is the entire point.
    assert (await _upload(admin, version_code=999)).status_code == 201


async def test_a_published_build_cannot_be_deleted(admin) -> None:
    """It is the distribution record, and a phone may be downloading it now."""
    version = (await _upload(admin)).json()["version"]
    await admin.post(f"/api/v1/app/versions/{version['id']}/publish")

    response = await admin.delete(f"/api/v1/app/versions/{version['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["detail"]["reason"] == "published"


async def test_the_uploader_comes_back_as_a_name(admin) -> None:
    """A manager cannot read `GET /users`, so an id alone renders as a uuid."""
    uploaded = (await _upload(admin)).json()["version"]
    assert uploaded["created_by_name"], "upload response carries the name"

    listed = (await admin.get("/api/v1/app/versions")).json()["items"][0]
    assert listed["created_by_name"] == uploaded["created_by_name"]
    assert listed["created_by"] == uploaded["created_by"]


async def test_a_manager_sees_the_uploader_name_without_users_read(
    admin, manager
) -> None:
    """The reason this is denormalised at all — checked from the role that has
    the problem, not from admin."""
    await _upload(admin)
    assert (await manager.get("/api/v1/users")).status_code == 403

    listed = (await manager.get("/api/v1/app/versions")).json()["items"][0]
    assert listed["created_by_name"]
    assert listed["created_by_name"] != listed["created_by"]


# --- The public download page's read (GET /api/v1/app/latest) ---------------
#
# Added 2026-09-14 so the site's front page can offer the app to somebody with
# no account. It is the same call SPEC §4.1 rule 5 already made about the
# binary; what these tests pin is the boundary around it.

LATEST = "/api/v1/app/latest"


async def test_the_public_list_needs_no_token(db, client, admin) -> None:
    uploaded = (await _upload(admin)).json()["version"]
    await admin.post(f"/api/v1/app/versions/{uploaded['id']}/publish")

    response = await client.get(LATEST)

    assert "authorization" not in {k.lower() for k in client.headers}
    assert response.status_code == 200
    assert [item["version_code"] for item in response.json()["items"]] == [140]


async def test_an_unpublished_build_is_not_offered(db, client, admin) -> None:
    """Upload and publish are two steps so a build can be inspected first.

    A page that handed out whatever was uploaded would undo that, and the
    person it would reach is a salesperson installing on their own phone.
    """
    await _upload(admin)

    assert (await client.get(LATEST)).json()["items"] == []


async def test_a_server_with_no_build_answers_an_empty_list_not_a_404(
    db, client
) -> None:
    """A fresh deployment has no APK. That is a state, not an error — the page
    says so in Uzbek rather than rendering a button that goes nowhere."""
    response = await client.get(LATEST)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


async def test_the_public_shape_never_names_the_member_of_staff(
    db, client, admin
) -> None:
    """The admin-facing model carries `created_by` and `created_by_name`.

    This one is a separate model rather than a subset of it, and this is the
    test that makes that choice load-bearing: reusing `AppVersionResponse`
    would publish which employee uploaded the build to anybody who asked.
    """
    uploaded = (await _upload(admin)).json()["version"]
    await admin.post(f"/api/v1/app/versions/{uploaded['id']}/publish")

    item = (await client.get(LATEST)).json()["items"][0]

    assert set(item) == {
        "version",
        "version_code",
        "variant",
        "size_bytes",
        "apk_sha256",
        "min_api_level",
        "release_notes_uz",
        "published_at",
    }


async def test_each_variant_is_offered_once(db, client, admin) -> None:
    """Both flavours ship in lockstep (SPEC §7.2) and a phone needs the one
    that matches its Android version, so the page shows both."""
    for code, variant in ((140, "modern34"), (141, "legacy28")):
        uploaded = (await _upload(admin, version_code=code, variant=variant)).json()
        await admin.post(f"/api/v1/app/versions/{uploaded['version']['id']}/publish")

    items = (await client.get(LATEST)).json()["items"]

    assert sorted(item["variant"] for item in items) == ["legacy28", "modern34"]


async def test_the_public_list_is_rate_limited(db, client) -> None:
    """It is anonymous, so it is bounded — loosely, because it is the front
    door and one office address is fifteen people."""
    limit = ratelimit.PUBLIC_RELEASE_PER_IP.requests
    assert limit > ratelimit.INSTALL_PAGE_PER_IP.requests
    for _ in range(limit):
        assert (await client.get(LATEST)).status_code == 200
    assert (await client.get(LATEST)).status_code == 429
