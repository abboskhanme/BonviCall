"""The gap report (T53, UC-23, N3, N4).

The report is the product's own smoke alarm, so the assertions here are about
the two ways it can lie: a denominator that includes calls nobody answered, and
totals that disagree with the call list it links to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.enums import AudioMissingReason, CallDisposition

pytestmark = pytest.mark.asyncio


async def test_the_denominator_is_answered_calls_only(
    manager, call_factory, installation_factory
) -> None:
    """SPEC §3.9: an unanswered call in the denominator makes '% of answered
    calls with audio' meaningless."""
    installation = await installation_factory()
    await call_factory(
        installation=installation, has_audio=True, audio_missing_reason=None
    )
    await call_factory(installation=installation)  # answered, awaiting audio
    await call_factory(
        installation=installation,
        disposition=CallDisposition.NO_ANSWER,
        audio_missing_reason=AudioMissingReason.NOT_EXPECTED,
    )

    body = (await manager.get("/api/v1/reports/gap")).json()
    assert body["answered_calls"] == 2, "the unanswered call is not in the denominator"
    assert body["calls_with_audio"] == 1
    assert Decimal(body["capture_rate"]) == Decimal("50.00")


async def test_the_totals_reconcile_with_the_call_list(
    manager, call_factory, installation_factory
) -> None:
    """UC-23: a report that disagrees with the list it links to is worse than
    no report."""
    installation = await installation_factory()
    for _ in range(3):
        await call_factory(installation=installation)
    await call_factory(
        installation=installation, has_audio=True, audio_missing_reason=None
    )

    report = (await manager.get("/api/v1/reports/gap")).json()
    listed = (
        await manager.get("/api/v1/calls?has_audio=false&with_total=true")
    ).json()
    assert report["missing_total"] == listed["total"] == 3


async def test_reasons_say_which_ones_count_against_the_rate(
    manager, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await call_factory(installation=installation)  # pending_upload
    await call_factory(
        installation=installation,
        audio_missing_reason=AudioMissingReason.NO_PERMISSION,
    )
    body = (await manager.get("/api/v1/reports/gap")).json()
    by_reason = {row["reason"]: row for row in body["by_reason"]}
    assert by_reason["pending_upload"]["counts_against_capture_rate"] is False
    assert by_reason["no_permission"]["counts_against_capture_rate"] is True


async def test_the_report_groups_by_agent(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """An admin's next question is always "whose phone"."""
    first = await agent_factory(full_name="Aziz")
    second = await agent_factory(full_name="Bekzod")
    await call_factory(
        installation=await installation_factory(agent=first),
        has_audio=True,
        audio_missing_reason=None,
    )
    await call_factory(installation=await installation_factory(agent=second))

    body = (await manager.get("/api/v1/reports/gap")).json()
    by_agent = {row["agent_name"]: row for row in body["by_agent"]}
    assert Decimal(by_agent["Aziz"]["capture_rate"]) == Decimal("100.00")
    assert Decimal(by_agent["Bekzod"]["capture_rate"]) == Decimal("0.00")


async def test_a_model_below_its_m0_baseline_is_flagged(
    db, manager, call_factory, installation_factory, device_factory
) -> None:
    """N4. Without a stored baseline, "capture is worse" is an opinion."""
    from src.core.enums import AppVariant, CaptureRoute
    from src.modules.catalog.models import SupportedModelModel

    db.add(
        SupportedModelModel(
            manufacturer="Xiaomi",
            model="Redmi Note 12",
            api_level=33,
            app_variant=AppVariant.MODERN34,
            capture_route=CaptureRoute.OEM_FILE_HARVEST,
            baseline_audio_capture_rate=Decimal("95.00"),
            baseline_sample_calls=40,
        )
    )
    await db.flush()

    installation = await installation_factory(device=await device_factory())
    for _ in range(3):
        await call_factory(installation=installation)  # no audio
    await call_factory(
        installation=installation, has_audio=True, audio_missing_reason=None
    )

    body = (await manager.get("/api/v1/reports/gap")).json()
    entry = next(r for r in body["by_model"] if r["model"] == "Redmi Note 12")
    assert Decimal(entry["capture_rate"]) == Decimal("25.00")
    assert Decimal(entry["baseline_rate"]) == Decimal("95.00")
    assert Decimal(entry["delta_pp"]) == Decimal("-70.00")
    assert entry["regression"] is True


async def test_a_model_at_its_baseline_is_not_flagged(
    db, manager, call_factory, installation_factory, device_factory
) -> None:
    from src.core.enums import AppVariant, CaptureRoute
    from src.modules.catalog.models import SupportedModelModel

    db.add(
        SupportedModelModel(
            manufacturer="Xiaomi",
            model="Redmi Note 12",
            api_level=33,
            app_variant=AppVariant.MODERN34,
            capture_route=CaptureRoute.OEM_FILE_HARVEST,
            baseline_audio_capture_rate=Decimal("95.00"),
        )
    )
    await db.flush()
    installation = await installation_factory(device=await device_factory())
    await call_factory(
        installation=installation, has_audio=True, audio_missing_reason=None
    )
    body = (await manager.get("/api/v1/reports/gap")).json()
    entry = next(r for r in body["by_model"] if r["model"] == "Redmi Note 12")
    assert entry["regression"] is False


async def test_an_open_call_log_delta_appears_after_a_day(
    db, manager, installation_factory
) -> None:
    """N3: a delta still open after 24 h is a real gap, not a slow upload."""
    from src.modules.devices.models import CallLogDeltaModel

    installation = await installation_factory()
    db.add(
        CallLogDeltaModel(
            installation_id=installation.id,
            number_id=installation.number_id,
            period_date=datetime.now(UTC).date(),
            device_counted=31,
            uploaded_count=28,
            subscription_unknown_count=2,
            first_reported_at=datetime.now(UTC) - timedelta(hours=30),
        )
    )
    await db.flush()

    body = (await manager.get("/api/v1/reports/gap")).json()
    assert len(body["open_deltas"]) == 1
    entry = body["open_deltas"][0]
    assert entry["delta"] == 3
    assert entry["subscription_unknown_count"] == 2, (
        "reported separately and never folded into the rate"
    )


async def test_a_fresh_delta_is_not_a_gap_yet(db, manager, installation_factory) -> None:
    from src.modules.devices.models import CallLogDeltaModel

    installation = await installation_factory()
    db.add(
        CallLogDeltaModel(
            installation_id=installation.id,
            number_id=installation.number_id,
            period_date=datetime.now(UTC).date(),
            device_counted=31,
            uploaded_count=28,
        )
    )
    await db.flush()
    body = (await manager.get("/api/v1/reports/gap")).json()
    assert body["open_deltas"] == []


async def test_the_report_needs_reports_read(sales, service_token, client) -> None:
    assert (await client.get("/api/v1/reports/gap")).status_code == 401
    assert (await sales.get("/api/v1/reports/gap")).status_code == 403
    assert (await service_token.get("/api/v1/reports/gap")).status_code == 403


async def test_an_empty_report_does_not_divide_by_zero(manager) -> None:
    body = (await manager.get("/api/v1/reports/gap")).json()
    assert body["answered_calls"] == 0
    assert body["capture_rate"] is None
