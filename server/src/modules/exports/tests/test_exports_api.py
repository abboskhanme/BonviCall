"""The service export (T51, T52; UC-29, §5.4).

A committed contract. The two properties release 2 depends on are cursor
stability and the audio reference; both are tested here rather than assumed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core.enums import AuditAction, CallDirection
from src.modules.audit.models import AuditLogModel

pytestmark = pytest.mark.asyncio

PAYLOAD = b"OggS" + bytes(range(256)) * 4


async def _age(db, call, seconds: int = 60) -> None:
    """Push a call outside the settling window so the export can see it."""
    call.received_at = datetime.now(UTC) - timedelta(seconds=seconds)
    await db.flush()


async def test_the_export_carries_everything_the_pipeline_needs(
    db, service_token, call_factory
) -> None:
    call = await call_factory(direction=CallDirection.OUTGOING)
    await _age(db, call)
    body = (await service_token.get("/api/service/v1/export/calls")).json()

    assert body["count"] == 1
    item = body["items"][0]
    assert item["bonvizvonki_direction"] == "outbound", "our vocabulary never leaks"
    assert item["agent_number_key"] and len(item["agent_number_key"]) == 9
    assert item["remote_number_key"] == "935554433"
    assert item["answered"] is True
    assert item["call_type"] and item["duration_sec"] == 120
    assert item["received_at"] and item["started_at"]


async def test_two_consecutive_full_passes_return_identical_rows(
    db, service_token, call_factory
) -> None:
    """UC-29's acceptance criterion, and the reason for the settling window."""
    for _ in range(5):
        await _age(db, await call_factory())

    async def full_pass() -> list[str]:
        seen: list[str] = []
        since = 0
        while True:
            body = (
                await service_token.get(
                    f"/api/service/v1/export/calls?since={since}&limit=2"
                )
            ).json()
            if not body["items"]:
                return seen
            seen.extend(item["id"] for item in body["items"])
            since = body["next_since"]

    first = await full_pass()
    second = await full_pass()
    assert first == second
    assert len(first) == len(set(first)) == 5


async def test_a_just_written_call_is_held_back_by_the_settling_window(
    db, service_token, call_factory
) -> None:
    """A lower ``seq`` can commit after a higher one, and a naive cursor would
    then skip it forever."""
    await call_factory()  # received_at = now
    body = (await service_token.get("/api/service/v1/export/calls")).json()
    assert body["count"] == 0


async def test_the_audio_reference_is_a_path_not_a_public_url(
    db, service_token, audio_factory
) -> None:
    """N20/§5.4: BonviZvonki streams the audio; it never gets a public URL."""
    audio = await audio_factory(payload=PAYLOAD)
    call = await db.get(
        __import__("src.modules.calls.models", fromlist=["CallModel"]).CallModel,
        audio.call_id,
    )
    await _age(db, call)
    item = (await service_token.get("/api/service/v1/export/calls")).json()["items"][0]
    assert item["audio_ref"] == f"/api/service/v1/export/calls/{call.id}/audio"
    assert item["audio_sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert not item["audio_ref"].startswith("http")


async def test_retention_removes_the_audio_reference(
    db, service_token, audio_factory
) -> None:
    """A reference to a file that is gone is worse than no reference."""
    from src.modules.audio.service import AudioService
    from src.modules.calls.models import CallModel

    audio = await audio_factory(payload=PAYLOAD)
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    call = await db.get(CallModel, audio.call_id)
    await _age(db, call)
    await AudioService(db).apply_retention()

    item = (await service_token.get("/api/service/v1/export/calls")).json()["items"][0]
    assert item["audio_ref"] is None
    assert item["audio_sha256"] is None


async def test_the_agent_export_carries_the_number_history(
    db, service_token, agent_factory, registered_number_factory
) -> None:
    """BonviZvonki's L3 failure was exactly this mapping arriving wrong."""
    agent = await agent_factory(full_name="Aziz Karimov")
    await registered_number_factory(agent=agent, e164="+998901112233")
    body = (await service_token.get("/api/service/v1/export/agents")).json()
    entry = next(i for i in body["items"] if i["full_name"] == "Aziz Karimov")
    assert entry["numbers"][0]["e164"] == "+998901112233"
    assert entry["numbers"][0]["key"] == "901112233"
    assert entry["numbers"][0]["valid_to"] is None


async def test_the_service_audio_endpoint_answers_range(
    db, service_token, audio_factory
) -> None:
    """N43/§5.4 consequence 2: streaming, not copying, is the whole point."""
    audio = await audio_factory(payload=PAYLOAD)
    response = await service_token.get(
        f"/api/service/v1/export/calls/{audio.call_id}/audio",
        headers={"Range": "bytes=10-59"},
    )
    assert response.status_code == 206
    assert response.content == PAYLOAD[10:60]
    assert response.headers["content-range"] == f"bytes 10-59/{len(PAYLOAD)}"


async def test_every_service_audio_access_is_audited(
    db, service_token, audio_factory
) -> None:
    audio = await audio_factory(payload=PAYLOAD)
    await service_token.get(f"/api/service/v1/export/calls/{audio.call_id}/audio")
    row = await db.scalar(
        sa.select(AuditLogModel).where(
            AuditLogModel.action == AuditAction.AUDIO_DOWNLOAD
        )
    )
    assert row is not None
    assert row.actor_type.value == "service"
    assert row.actor_service_token_id is not None


async def test_a_service_token_cannot_write_read_users_or_read_audit(
    service_token, agent_factory
) -> None:
    """UC-29's acceptance criterion, asserted rather than assumed."""
    assert (await service_token.get("/api/v1/users")).status_code == 403
    assert (await service_token.get("/api/v1/audit")).status_code == 403
    assert (
        await service_token.post("/api/v1/agents", json={"full_name": "Nope"})
    ).status_code == 403
    assert (await service_token.get("/api/v1/calls")).status_code == 403


async def test_a_scoped_token_cannot_reach_beyond_its_scope(db, app) -> None:
    """Scopes narrow the role further: a callback token cannot read the export."""
    import uuid as _uuid

    from httpx import ASGITransport, AsyncClient

    from src.core.deps import Principal, get_current_principal
    from src.core.permissions import Role

    principal = Principal(
        kind="service",
        id=_uuid.uuid4(),
        role=str(Role.SERVICE),
        permissions=frozenset({"callback:report"}),
    )
    app.dependency_overrides[get_current_principal] = lambda: principal
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/api/service/v1/export/calls")).status_code == 403


async def test_the_export_needs_a_token(client) -> None:
    assert (await client.get("/api/service/v1/export/calls")).status_code == 401


async def test_a_panel_manager_cannot_read_the_machine_export(manager) -> None:
    """``export:read`` is admin and service only; a manager uses the panel."""
    assert (await manager.get("/api/service/v1/export/calls")).status_code == 403
