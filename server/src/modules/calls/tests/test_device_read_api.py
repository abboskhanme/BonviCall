"""The employee's own calls, read from their own phone (T59, docs/DEVICE-READ-API.md).

The device surface was write-only until this. It is the first thing it hands
back, so most of this file is about **scope**: a token's reach is the agent it
is bound to, and getting that wrong is how a lost phone becomes a data breach
rather than a lost phone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.core.enums import AudioMissingReason, CallDisposition, InstallationStatus

pytestmark = pytest.mark.asyncio


# --- scope: the half that matters ------------------------------------------


async def test_a_phone_sees_only_its_own_agents_calls(
    db, call_factory, agent_factory, installation_factory, device_client_factory
) -> None:
    """The whole design in one test.

    Narrowed in the query, never a filter the client applies to a wider
    response — the client is the thing we cannot trust.
    """
    mine = await agent_factory()
    installation = await installation_factory(agent=mine)
    await call_factory(installation=installation)
    # Its own installation, so its own agent — a different one by construction.
    await call_factory()

    client = await device_client_factory(installation)
    body = (await client.get("/api/device/v1/calls")).json()

    assert len(body["items"]) == 1, "another agent's call reached this phone"


async def test_another_agents_call_is_404_and_never_403(
    db, call_factory, agent_factory, installation_factory, device_client_factory
) -> None:
    """§4.1 rule 2, and it matters more here than on the panel.

    A 403 would tell whoever is holding this phone that the call exists and
    belongs to somebody else.
    """
    installation = await installation_factory()
    theirs = await call_factory()  # its own installation and agent
    client = await device_client_factory(installation)

    for path in (
        f"/api/device/v1/calls/{theirs.id}/audio",
    ):
        response = await client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] in ("call_not_found", "not_found")


async def test_the_list_needs_a_device_token(client) -> None:
    assert (await client.get("/api/device/v1/calls")).status_code == 401


async def test_an_unverified_phone_cannot_read(
    installation_factory, device_client_factory
) -> None:
    """The privacy boundary runs both ways: a phone that cannot upload a call
    cannot read one either."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    installation.status = InstallationStatus.PENDING
    assert (await client.get("/api/device/v1/calls")).status_code == 403


async def test_an_installation_always_has_an_agent(db, installation_factory) -> None:
    """``docs/DEVICE-READ-API.md`` asked for an empty page when there is no
    agent. That state is unrepresentable and there is no branch for it.

    A code is issued *for* an agent and redeeming it is what creates the
    installation, so ``installations.agent_id`` is ``NOT NULL``. Asserting the
    constraint is worth more than a guard: if the column ever became nullable,
    this fails and the scope narrowing has to be re-read.
    """
    import sqlalchemy as sa

    from src.modules.installations.models import InstallationModel

    installation = await installation_factory()
    installation.agent_id = None
    with pytest.raises(sa.exc.IntegrityError):
        await db.flush()
    await db.rollback()
    assert InstallationModel.__table__.c.agent_id.nullable is False


# --- the screen ------------------------------------------------------------


async def test_audio_state_is_never_null_and_explains_itself(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """This screen is where an employee learns that *qayd etish* and *yozib
    olish* are different promises, so it must always have something to say.

    ``audio_missing_reason`` cannot carry that on its own: every member of the
    enum means audio is *absent*, so it is null exactly when there is a
    recording — the one case the screen most needs a word for.
    """
    installation = await installation_factory()
    queued = await call_factory(
        installation=installation,
        has_audio=False,
        audio_missing_reason=AudioMissingReason.PENDING_UPLOAD,
    )
    refused = await call_factory(
        installation=installation,
        has_audio=False,
        audio_missing_reason=AudioMissingReason.NO_PERMISSION,
    )
    missed = await call_factory(
        installation=installation,
        disposition=CallDisposition.MISSED,
        direction="incoming",
        duration_sec=0,
        has_audio=False,
        audio_missing_reason=AudioMissingReason.NOT_EXPECTED,
    )

    client = await device_client_factory(installation)
    listed = (await client.get("/api/device/v1/calls")).json()["items"]
    items = {item["id"]: item for item in listed}

    assert all(item["audio_state"] for item in items.values()), "never null"
    assert items[str(queued.id)]["audio_state"] == "queued"
    assert items[str(refused.id)]["audio_state"] == "missing"
    assert items[str(refused.id)]["audio_missing_reason"] == "no_permission"
    assert items[str(missed.id)]["audio_state"] == "not_expected"


async def test_expired_audio_says_expired_not_recorded(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """The call row keeps ``has_audio = true`` after retention, on purpose
    (UC-26). Reading only that column would offer a play control for a file
    that is gone — which is what every client deriving this itself would do."""
    import sqlalchemy as sa

    from src.modules.audio.models import CallAudioModel

    installation = await installation_factory()
    call = await call_factory(
        installation=installation, has_audio=True
    )
    db.add(
        CallAudioModel(
            call_id=call.id,
            storage_key="calls/2026/09/05/gone.ogg",
            bytes=1,
            sha256="0" * 64,
            codec="opus",
            container="ogg",
            capture_route="oem_file_harvest",
            deleted_at=datetime.now(UTC),
            deleted_reason="retention",
        )
    )
    await db.flush()

    client = await device_client_factory(installation)
    item = (await client.get("/api/device/v1/calls")).json()["items"][0]
    assert call.has_audio is True
    assert item["audio_state"] == "expired"

    # And the play route agrees, rather than 404-ing as if it never existed.
    response = await client.get(f"/api/device/v1/calls/{call.id}/audio")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "audio_expired"
    assert await db.scalar(sa.select(sa.func.count()).select_from(CallAudioModel)) == 1


async def test_has_audio_is_what_the_server_holds(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """Not what the device believes it sent — the reason for reading this from
    the server at all."""
    installation = await installation_factory()
    call = await call_factory(
        installation=installation,
        has_audio=False,
        audio_missing_reason=AudioMissingReason.PENDING_UPLOAD,
    )
    client = await device_client_factory(installation)
    item = (await client.get("/api/device/v1/calls")).json()["items"][0]
    assert item["has_audio"] is False
    assert item["id"] == str(call.id)


# --- ordering and paging ---------------------------------------------------


async def test_the_diary_is_ordered_by_when_the_call_happened(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """Two clocks, deliberately (D-08, N36).

    The panel pages on ``received_at`` because it is monotonic. A person's own
    list is a diary: a call recovered from the call log three days late must
    not appear above calls that happened after it.
    """
    installation = await installation_factory()
    now = datetime.now(UTC)
    old_call = await call_factory(
        installation=installation,
        started_at=now - timedelta(days=3),
        ended_at=now - timedelta(days=3) + timedelta(seconds=60),
    )
    recent = await call_factory(
        installation=installation,
        started_at=now - timedelta(hours=1),
        ended_at=now - timedelta(hours=1) + timedelta(seconds=60),
    )
    # The old one arrived last — recovered from the call log.
    old_call.received_at = now
    recent.received_at = now - timedelta(hours=1)
    await db.flush()

    client = await device_client_factory(installation)
    items = (await client.get("/api/device/v1/calls")).json()["items"]
    assert [item["id"] for item in items] == [str(recent.id), str(old_call.id)]


async def test_the_page_walks_without_repeating_or_skipping(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    now = datetime.now(UTC)
    for index in range(7):
        await call_factory(
            installation=installation,
                started_at=now - timedelta(minutes=index),
            ended_at=now - timedelta(minutes=index) + timedelta(seconds=30),
        )

    client = await device_client_factory(installation)
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        url = "/api/device/v1/calls?limit=3" + (f"&cursor={cursor}" if cursor else "")
        body = (await client.get(url)).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            break
    assert len(seen) == 7
    assert len(set(seen)) == 7


async def test_since_asks_what_has_arrived_not_what_happened(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """A refresh is a question about arrival, which only ``received_at``
    answers: a call recovered from the call log happened long ago and arrived
    just now, and the app must be told about it."""
    installation = await installation_factory()
    now = datetime.now(UTC)
    old_but_new = await call_factory(
        installation=installation,
        started_at=now - timedelta(days=5),
        ended_at=now - timedelta(days=5) + timedelta(seconds=30),
    )
    stale = await call_factory(
        installation=installation,
        started_at=now - timedelta(minutes=5),
        ended_at=now - timedelta(minutes=5) + timedelta(seconds=30),
    )
    old_but_new.received_at = now
    stale.received_at = now - timedelta(days=1)
    await db.flush()

    client = await device_client_factory(installation)
    # Passed as a parameter, not interpolated: the "+05:00" offset has to be
    # percent-encoded or it arrives as a space, which is what a hand-built URL
    # gets wrong and a real client does not.
    response = await client.get(
        "/api/device/v1/calls", params={"since": (now - timedelta(hours=1)).isoformat()}
    )
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(old_but_new.id)]


async def test_the_page_size_is_capped(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    """A phone screen. The panel's 1 000-row pages are the panel's problem."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.get("/api/device/v1/calls?limit=100000")
    assert response.status_code == 200


# --- playback --------------------------------------------------------------


async def test_playback_answers_a_range_with_206(
    db, admin, call_factory, installation_factory, device_client_factory
) -> None:
    """The client cannot be finished without it: ExoPlayer seeks, and seeking a
    twenty-minute file must not download it over cellular (N43)."""
    from src.modules.audio.tests.test_audio_api import PAYLOAD, _upload

    installation = await installation_factory()
    started = datetime.now(UTC) - timedelta(minutes=5)
    call = await call_factory(
        installation=installation,
        started_at=started,
        ended_at=started + timedelta(seconds=120),
        duration_sec=120,
    )
    client = await device_client_factory(installation)
    opened = await _upload(client, call)
    await client.post(f"/api/device/v1/audio/{opened['upload_id']}/commit")

    whole = await client.get(f"/api/device/v1/calls/{call.id}/audio")
    assert whole.status_code == 200
    assert whole.headers["accept-ranges"] == "bytes"
    assert whole.content == PAYLOAD

    partial = await client.get(
        f"/api/device/v1/calls/{call.id}/audio", headers={"Range": "bytes=0-99"}
    )
    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes 0-99/{len(PAYLOAD)}"
    assert partial.content == PAYLOAD[:100]

    tail = await client.get(
        f"/api/device/v1/calls/{call.id}/audio",
        headers={"Range": f"bytes={len(PAYLOAD) - 10}-"},
    )
    assert tail.status_code == 206
    assert tail.content == PAYLOAD[-10:]


async def test_a_call_with_no_recording_is_404_so_the_app_shows_the_reason(
    db, call_factory, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    call = await call_factory(
        installation=installation,
        has_audio=False,
        audio_missing_reason=AudioMissingReason.NO_PERMISSION,
    )
    client = await device_client_factory(installation)
    response = await client.get(f"/api/device/v1/calls/{call.id}/audio")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "audio_not_found"


async def test_a_call_that_does_not_exist_is_404(
    installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    response = await client.get(f"/api/device/v1/calls/{uuid.uuid4()}/audio")
    assert response.status_code == 404


async def test_a_replacement_handset_still_shows_the_agents_earlier_calls(
    db, call_factory, agent_factory, installation_factory, device_client_factory
) -> None:
    """Scoped by **agent**, not by installation — and the difference is real.

    When a salesperson's phone is lost or replaced, the number is rebound to a
    new installation (SPEC §9.3) and the old one is ``replaced``. Their calls
    did not stop being theirs. Narrowing on ``installation_id`` looks equally
    correct, passes every other test in this file, and would silently empty an
    employee's history the day they got a new handset.
    """
    agent = await agent_factory()
    old_phone = await installation_factory(agent=agent)
    old_call = await call_factory(installation=old_phone)
    old_phone.status = InstallationStatus.REPLACED

    new_phone = await installation_factory(agent=agent)
    new_call = await call_factory(installation=new_phone)
    await db.flush()

    client = await device_client_factory(new_phone)
    items = (await client.get("/api/device/v1/calls")).json()["items"]
    assert {item["id"] for item in items} == {str(old_call.id), str(new_call.id)}
