"""Reference data: the line directory and the published build (T49, N33)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.enums import AppVariant
from src.modules.catalog.models import AppVersionModel
from src.modules.catalog.service import CatalogService

pytestmark = pytest.mark.asyncio


async def test_the_directory_rules_are_digits_only(db, admin) -> None:
    """UC-25's ``*700`` is a suffix rule; the star is notation, not data."""
    await admin.post("/api/v1/line-directory", json={"pattern": "*700", "kind": "suffix"})
    rules = await CatalogService(db).directory_rules()
    assert rules == (("suffix", "700"),)


async def test_a_deactivated_rule_leaves_the_directory(db, admin) -> None:
    created = await admin.post(
        "/api/v1/line-directory", json={"pattern": "700", "kind": "suffix"}
    )
    await admin.delete(f"/api/v1/line-directory/{created.json()['entry']['id']}")
    assert await CatalogService(db).directory_rules() == ()


async def test_re_adding_a_removed_rule_reactivates_it(db, admin) -> None:
    """Deactivated rather than deleted, so the audit trail keeps the row."""
    created = await admin.post(
        "/api/v1/line-directory", json={"pattern": "700", "kind": "suffix"}
    )
    entry_id = created.json()["entry"]["id"]
    await admin.delete(f"/api/v1/line-directory/{entry_id}")
    again = await admin.post(
        "/api/v1/line-directory", json={"pattern": "700", "kind": "suffix"}
    )
    assert again.json()["entry"]["id"] == entry_id


async def test_a_pattern_with_no_digits_is_refused(admin) -> None:
    response = await admin.post(
        "/api/v1/line-directory", json={"pattern": "**", "kind": "suffix"}
    )
    assert response.status_code == 409


async def test_there_is_no_published_build_until_one_is_published(db) -> None:
    """``None`` is a real answer, and the install page says so in Uzbek rather
    than offering a dead button."""
    service = CatalogService(db)
    assert await service.current_version_code() is None

    db.add(
        AppVersionModel(
            version="1.0.0",
            version_code=100,
            variant=AppVariant.MODERN34,
            apk_path="releases/x.apk",
            apk_sha256="e" * 64,
            size_bytes=1,
            is_current=True,
            published_at=None,
        )
    )
    await db.flush()
    assert await service.current_version_code() is None, "uploaded is not published"


async def test_the_published_build_is_the_current_one(db) -> None:
    db.add(
        AppVersionModel(
            version="1.0.0",
            version_code=100,
            variant=AppVariant.MODERN34,
            apk_path="releases/x.apk",
            apk_sha256="e" * 64,
            size_bytes=1,
            is_current=True,
            published_at=datetime.now(UTC),
        )
    )
    await db.flush()
    service = CatalogService(db)
    assert await service.current_version_code() == 100
    assert (await service.current_release()).version == "1.0.0"


async def test_one_current_build_per_variant(db) -> None:
    """A partial unique index; two "current" builds is a coin toss at install."""
    from sqlalchemy.exc import IntegrityError

    for _ in range(2):
        db.add(
            AppVersionModel(
                version=f"1.0.{_}",
                version_code=100 + _,
                variant=AppVariant.MODERN34,
                apk_path="releases/x.apk",
                apk_sha256=str(_) * 64,
                size_bytes=1,
                is_current=True,
            )
        )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()
