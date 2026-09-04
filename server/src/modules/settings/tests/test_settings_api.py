"""The settings API and the retention confirmation gate (T58, SPEC §3.11)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.core.enums import AuditAction
from src.core.settings_keys import ALL_SETTING_KEYS, DEVICE_VISIBLE_KEYS, SettingKey
from src.modules.audit.models import AuditLogModel
from src.modules.settings.models import AppSettingModel

pytestmark = pytest.mark.asyncio


async def test_every_declared_key_is_seeded(db) -> None:
    """SPEC §3.8: a missing key is a bug, not a silent ``None``.

    The constants and the migration's seed are two lists; this is what keeps
    them equal.
    """
    seeded = set((await db.scalars(sa.select(AppSettingModel.key))).all())
    assert ALL_SETTING_KEYS == seeded


async def test_nothing_hard_codes_a_threshold(admin) -> None:
    body = (await admin.get("/api/v1/settings")).json()
    assert body["total"] == len(ALL_SETTING_KEYS)


async def test_an_admin_can_change_a_threshold(db, admin) -> None:
    response = await admin.put(
        "/api/v1/settings",
        json={"key": SettingKey.ALERTS_SILENCE_HOURS, "value": 6},
    )
    assert response.status_code == 200
    assert response.json()["value"] == 6
    row = await db.get(AppSettingModel, SettingKey.ALERTS_SILENCE_HOURS)
    assert row.value == 6


async def test_shortening_retention_needs_an_explicit_confirmation(admin) -> None:
    """SPEC §3.11: the change deletes recordings that still exist."""
    refused = await admin.put(
        "/api/v1/settings",
        json={"key": SettingKey.RETENTION_AUDIO_MONTHS, "value": 1},
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "retention_confirmation_required"
    assert refused.json()["error"]["detail"]["confirm_below_months"] == 3

    accepted = await admin.put(
        "/api/v1/settings",
        json={"key": SettingKey.RETENTION_AUDIO_MONTHS, "value": 1, "confirm": True},
    )
    assert accepted.status_code == 200


async def test_a_refused_change_changes_nothing(db, admin) -> None:
    await admin.put(
        "/api/v1/settings",
        json={"key": SettingKey.RETENTION_AUDIO_MONTHS, "value": 1},
    )
    row = await db.get(AppSettingModel, SettingKey.RETENTION_AUDIO_MONTHS)
    assert row.value == 12


async def test_lengthening_retention_needs_no_confirmation(admin) -> None:
    """It destroys nothing, so asking would be a habit rather than a guard."""
    response = await admin.put(
        "/api/v1/settings",
        json={"key": SettingKey.RETENTION_AUDIO_MONTHS, "value": 24},
    )
    assert response.status_code == 200


async def test_retention_changes_are_filterable_on_their_own(db, admin) -> None:
    """It is the one setting whose change destroys data; "who shortened
    retention, and when" must be one filter, not a JSONB dig."""
    await admin.put(
        "/api/v1/settings",
        json={"key": SettingKey.RETENTION_AUDIO_MONTHS, "value": 2, "confirm": True},
    )
    await admin.put(
        "/api/v1/settings", json={"key": SettingKey.ALERTS_SILENCE_HOURS, "value": 5}
    )
    retention = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.RETENTION_CHANGED)
    )
    ordinary = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.SETTING_UPDATED)
    )
    assert retention == 1 and ordinary == 1


async def test_an_unknown_key_is_404(admin) -> None:
    """The key set is closed, so a typo cannot create a setting nobody reads."""
    response = await admin.put(
        "/api/v1/settings", json={"key": "retention.audio_days", "value": 1}
    )
    assert response.status_code == 404


async def test_a_manager_reads_but_does_not_write(manager) -> None:
    assert (await manager.get("/api/v1/settings")).status_code == 200
    response = await manager.put(
        "/api/v1/settings", json={"key": SettingKey.ALERTS_SILENCE_HOURS, "value": 6}
    )
    assert response.status_code == 403


async def test_sales_and_viewer_see_no_settings(sales, viewer, client) -> None:
    assert (await sales.get("/api/v1/settings")).status_code == 403
    assert (await viewer.get("/api/v1/settings")).status_code == 403
    assert (await client.get("/api/v1/settings")).status_code == 401


async def test_the_device_config_is_an_allow_list(db) -> None:
    """A handset has no business knowing the retention period or the alert
    e-mail list, so the block it receives is named rather than dumped."""
    from src.modules.settings.service import SettingsService

    config = await SettingsService(db).device_config()
    assert set(config) == DEVICE_VISIBLE_KEYS
    assert SettingKey.RETENTION_AUDIO_MONTHS not in config
    assert SettingKey.ALERTS_EMAIL_TO not in config
