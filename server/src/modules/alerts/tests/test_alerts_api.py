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


def test_every_alert_kind_has_uzbek_text() -> None:
    """§14: every string an end user reads is Uzbek, including the new kinds.

    ``alert_text`` used to fall back to ``kind.replace("_", " ").capitalize()``,
    which put the English "Device offline" into ``title_uz`` — a field whose
    name promises otherwise — and the generic error body into ``body_uz`` for
    all 27 kinds. The panel had to route around both.
    """
    from src.core.enums import AlertKind
    from src.core.messages_uz import ALERT_TEXT, DEFAULT_MESSAGE, UNKNOWN_ALERT_TITLE

    missing = sorted(kind.value for kind in AlertKind if kind.value not in ALERT_TEXT)
    assert missing == [], (
        f"no Uzbek text for: {missing}. Add it to ALERT_TEXT in "
        "core/messages_uz.py — the fallback is deliberately vague and a new "
        "alert nobody can act on is an alert nobody acts on."
    )

    generic = sorted(
        kind
        for kind, (title, body) in ALERT_TEXT.items()
        if body == DEFAULT_MESSAGE or title == UNKNOWN_ALERT_TITLE
    )
    assert generic == [], f"these say nothing about what happened: {generic}"


def test_no_alert_text_is_english() -> None:
    """A cheap check that catches the failure that actually happened.

    Not a language detector: it looks for the words that were literally there,
    plus the give-away that a title is just the enum name with the underscores
    taken out.
    """
    from src.core.enums import AlertKind
    from src.core.messages_uz import ALERT_TEXT

    offenders = [
        kind
        for kind in AlertKind
        if ALERT_TEXT[kind.value][0].lower() == kind.value.replace("_", " ")
    ]
    assert offenders == [], (
        f"the title is the enum name in English: {offenders}"
    )


def test_the_alert_body_says_something_different_per_kind() -> None:
    """27 identical bodies is a shrug with a timestamp."""
    from src.core.messages_uz import ALERT_TEXT

    bodies = [body for _, body in ALERT_TEXT.values()]
    assert len(set(bodies)) == len(bodies), "two alert kinds share a body"


async def test_the_api_serves_current_wording_not_the_stored_copy(
    db, admin, installation_factory
) -> None:
    """An alert open since before a wording fix still reads correctly.

    The stored copy is the record of what the alert said when it was raised.
    Serving it is why every alert on the running server still read the English
    "Device offline" after the text had been written in Uzbek.
    """
    from src.core.enums import AlertKind, AlertSeverity
    from src.core.messages_uz import alert_text
    from src.modules.alerts.service import AlertService

    installation = await installation_factory()
    alert = await AlertService(db).raise_alert(
        kind=AlertKind.DEVICE_OFFLINE,
        severity=AlertSeverity.WARNING,
        scope=installation.id,
        installation_id=installation.id,
    )
    # Whatever shipped when it was raised — here, the old English title.
    alert.title_uz = "Device offline"
    alert.body_uz = "Xatolik yuz berdi. Administratorga murojaat qiling."
    await db.flush()

    body = (await admin.get("/api/v1/alerts")).json()
    served = next(item for item in body["items"] if item["id"] == str(alert.id))
    expected_title, expected_body = alert_text("device_offline")
    assert served["title_uz"] == expected_title
    assert served["body_uz"] == expected_body
    assert served["title_uz"] != "Device offline"
