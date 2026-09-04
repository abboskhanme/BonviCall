"""The alerts inbox and its dedupe rule (T39, UC-06, UC-18)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from src.core.enums import AlertKind, AlertSeverity, AuditAction
from src.modules.alerts.models import AlertModel
from src.modules.alerts.service import AlertService, dedupe_key
from src.modules.audit.models import AuditLogModel

pytestmark = pytest.mark.asyncio


async def test_the_dedupe_key_is_kind_plus_scope() -> None:
    """SPEC §3.8: ``<kind>:<installation|agent|model|fleet>``."""
    assert dedupe_key(AlertKind.DEVICE_OFFLINE, "abc") == "device_offline:abc"
    assert dedupe_key(AlertKind.FLEET_SILENT, None) == "fleet_silent:fleet"


async def test_one_open_alert_per_cause(db, installation_factory) -> None:
    """A phone reporting every two minutes must not produce 720 rows a day."""
    installation = await installation_factory()
    service = AlertService(db)
    for _ in range(5):
        await service.raise_alert(
            kind=AlertKind.DEVICE_OFFLINE,
            severity=AlertSeverity.WARNING,
            scope=installation.id,
            installation_id=installation.id,
        )
    rows = (await db.scalars(sa.select(AlertModel))).all()
    assert len(rows) == 1
    assert rows[0].occurrence_count == 5
    assert rows[0].last_seen_at >= rows[0].first_seen_at


async def test_two_causes_are_two_alerts(db, installation_factory) -> None:
    installation = await installation_factory()
    service = AlertService(db)
    await service.raise_alert(
        kind=AlertKind.DEVICE_OFFLINE,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
    )
    await service.raise_alert(
        kind=AlertKind.QUEUE_FULL,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
    )
    assert await db.scalar(sa.select(sa.func.count()).select_from(AlertModel)) == 2


async def test_the_wording_comes_from_the_catalogue(db, installation_factory) -> None:
    """§14: a service names the cause, it never writes the sentence."""
    from src.core.messages_uz import alert_text

    installation = await installation_factory()
    alert = await AlertService(db).raise_alert(
        kind=AlertKind.INSTALLATION_REBOUND,
        severity=AlertSeverity.WARNING,
        scope=installation.number_id,
    )
    assert (alert.title_uz, alert.body_uz) == alert_text("installation_rebound")


async def test_a_resolved_cause_can_raise_again(db, installation_factory) -> None:
    """The partial unique index is on the *open* rows, so a phone that goes
    offline twice leaves two rows and two stories."""
    installation = await installation_factory()
    service = AlertService(db)
    await service.raise_alert(
        kind=AlertKind.DEVICE_OFFLINE,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
    )
    await service.resolve(AlertKind.DEVICE_OFFLINE, installation.id)
    await service.raise_alert(
        kind=AlertKind.DEVICE_OFFLINE,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
    )
    assert await db.scalar(sa.select(sa.func.count()).select_from(AlertModel)) == 2


async def test_acknowledging_is_audited_and_idempotent(
    db, admin, installation_factory
) -> None:
    installation = await installation_factory()
    alert = await AlertService(db).raise_alert(
        kind=AlertKind.QUEUE_FULL,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
    )
    await db.flush()
    first = await admin.post(f"/api/v1/alerts/{alert.id}/ack")
    second = await admin.post(f"/api/v1/alerts/{alert.id}/ack")
    assert first.status_code == second.status_code == 200
    assert first.json()["acknowledged_at"] == second.json()["acknowledged_at"]

    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.ALERT_ACKNOWLEDGED)
    )
    assert rows == 1


async def test_an_alert_can_be_acknowledged_but_never_deleted(admin) -> None:
    """UC-06/UC-18: an alert that can be deleted is an alert that can be hidden."""
    from fastapi.routing import APIRoute

    from src.main import create_app

    for route in create_app().routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/alerts"):
            assert "DELETE" not in route.methods, route.path


async def test_the_inbox_filters_by_severity_and_open_state(
    db, admin, installation_factory
) -> None:
    installation = await installation_factory()
    service = AlertService(db)
    critical = await service.raise_alert(
        kind=AlertKind.CREDENTIAL_REPLAY,
        severity=AlertSeverity.CRITICAL,
        scope=installation.id,
    )
    await service.raise_alert(
        kind=AlertKind.QUEUE_FULL,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
    )
    await db.flush()

    body = (await admin.get("/api/v1/alerts?severity=critical")).json()
    assert [row["id"] for row in body["items"]] == [str(critical.id)]
    assert body["open_count"] == 2

    await admin.post(f"/api/v1/alerts/{critical.id}/ack")
    assert (await admin.get("/api/v1/alerts")).json()["open_count"] == 1


async def test_reading_alerts_needs_a_permission(sales, service_token, client) -> None:
    assert (await client.get("/api/v1/alerts")).status_code == 401
    assert (await sales.get("/api/v1/alerts")).status_code == 403
    assert (await service_token.get("/api/v1/alerts")).status_code == 403
