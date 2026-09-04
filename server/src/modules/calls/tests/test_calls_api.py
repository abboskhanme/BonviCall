"""Call ingest and the panel call list (T25, T45, T46, T47).

The idempotency tests here are the M1 acceptance criterion: the same payload
twice must produce one row and the same id. Everything else in the pipeline —
the Room queue, the retry backoff, the recovery sweep — is built on the
assumption that a resend is free, and it is only free if this holds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core.enums import (
    AudioMissingReason,
    CallDirection,
    CallDisposition,
    CallType,
    InstallationStatus,
)
from src.modules.calls.models import CallModel

pytestmark = pytest.mark.asyncio

STARTED_AT = datetime(2026, 9, 4, 8, 59, 2, tzinfo=UTC)


def call_payload(**overrides) -> dict:
    """One well-formed call, as the app would send it."""
    payload = {
        "client_call_id": str(uuid.uuid4()),
        "direction": "outgoing",
        "disposition": "answered",
        "remote_number": "+998935554433",
        "contact_name": "Anvar do'kon",
        "started_at": STARTED_AT.isoformat(),
        "answered_at": (STARTED_AT + timedelta(seconds=9)).isoformat(),
        "ended_at": (STARTED_AT + timedelta(seconds=522)).isoformat(),
        "duration_sec": 513,
        "ring_sec": 9,
        "sim_subscription_id": 2,
        "sim_slot": 1,
        "source": "live_capture",
        "reconciled_with_call_log": True,
        "audio_expected": True,
        "device_epoch_ms": int(STARTED_AT.timestamp() * 1000),
        "device_timezone": "Asia/Tashkent",
        "device_rtt_ms": 180,
        "app_version": "1.0.0",
        "app_variant": "modern34",
    }
    payload.update(overrides)
    return payload


async def _post(client, **overrides):
    return await client.post(
        "/api/device/v1/calls", json={"calls": [call_payload(**overrides)]}
    )


# --- Idempotency: the M1 contract -------------------------------------------


async def test_the_same_payload_twice_creates_one_row_with_one_id(
    db, installation_factory, device_client_factory
) -> None:
    """UC-12 / N2: a resend after a lost response must not duplicate a call."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    payload = call_payload()

    first = await client.post("/api/device/v1/calls", json={"calls": [payload]})
    second = await client.post("/api/device/v1/calls", json={"calls": [payload]})

    assert first.status_code == 200 and second.status_code == 200
    first_result = first.json()["results"][0]
    second_result = second.json()["results"][0]
    assert first_result["status"] == "created"
    assert second_result["status"] == "unchanged"
    assert first_result["id"] == second_result["id"]

    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(CallModel)
        .where(CallModel.client_call_id == uuid.UUID(payload["client_call_id"]))
    )
    assert rows == 1


async def test_a_reconciliation_correction_updates_the_same_row(
    db, installation_factory, device_client_factory
) -> None:
    """SPEC §3.10 rule 3: the app corrects an existing id, it never mints a new one."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    payload = call_payload(duration_sec=100, reconciled_with_call_log=False)
    created = (await client.post("/api/device/v1/calls", json={"calls": [payload]})).json()

    payload["duration_sec"] = 513
    payload["reconciled_with_call_log"] = True
    updated = (await client.post("/api/device/v1/calls", json={"calls": [payload]})).json()

    assert updated["results"][0]["status"] == "updated"
    assert updated["results"][0]["id"] == created["results"][0]["id"]
    call = await db.get(CallModel, uuid.UUID(updated["results"][0]["id"]))
    await db.refresh(call)
    assert call.duration_sec == 513 and call.reconciled_with_call_log is True


async def test_immutable_fields_survive_a_correction(
    db, installation_factory, device_client_factory, agent_factory
) -> None:
    """A device must not be able to move a call to another agent by resending."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    payload = call_payload()
    created = (await client.post("/api/device/v1/calls", json={"calls": [payload]})).json()
    call_id = uuid.UUID(created["results"][0]["id"])
    call = await db.get(CallModel, call_id)
    original = (call.number_id, call.agent_id, call.installation_id, call.received_at)

    payload["remote_number"] = "+998901234567"
    await client.post("/api/device/v1/calls", json={"calls": [payload]})
    await db.refresh(call)
    assert (call.number_id, call.agent_id, call.installation_id, call.received_at) == original


async def test_a_replay_from_another_installation_is_refused(
    db, installation_factory, device_client_factory, agent_factory, registered_number_factory
) -> None:
    """SPEC §3.10 rule 5: two devices claiming one call needs a human.

    Nothing is stored and a ``credential_replay`` alert is raised — this is
    either a bug or a stolen credential, and we cannot tell which.
    """
    from src.core.enums import AlertKind
    from src.modules.alerts.models import AlertModel

    first_installation = await installation_factory()
    other_agent = await agent_factory()
    other_number = await registered_number_factory(agent=other_agent)
    second_installation = await installation_factory(
        agent=other_agent, number=other_number
    )

    first_client = await device_client_factory(first_installation)
    second_client = await device_client_factory(second_installation)
    payload = call_payload()

    await first_client.post("/api/device/v1/calls", json={"calls": [payload]})
    response = await second_client.post("/api/device/v1/calls", json={"calls": [payload]})

    assert response.status_code == 200, "the batch still answers 200; the item failed"
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["error"]["code"] == "call_identity_conflict"

    rows = await db.scalar(
        sa.select(sa.func.count())
        .select_from(CallModel)
        .where(CallModel.client_call_id == uuid.UUID(payload["client_call_id"]))
    )
    assert rows == 1, "nothing new is stored"
    alerts = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.kind == AlertKind.CREDENTIAL_REPLAY)
    )
    assert alerts == 1


async def test_one_bad_item_does_not_fail_the_batch(
    db, installation_factory, device_client_factory, agent_factory, registered_number_factory
) -> None:
    """SPEC §4.4 rule 6: a batch that fails wholesale is retried forever."""
    first_installation = await installation_factory()
    other_agent = await agent_factory()
    second_installation = await installation_factory(
        agent=other_agent, number=await registered_number_factory(agent=other_agent)
    )
    stolen = call_payload()
    await (await device_client_factory(first_installation)).post(
        "/api/device/v1/calls", json={"calls": [stolen]}
    )

    client = await device_client_factory(second_installation)
    good = call_payload()
    response = await client.post(
        "/api/device/v1/calls", json={"calls": [stolen, good]}
    )
    results = {item["client_call_id"]: item for item in response.json()["results"]}
    assert results[stolen["client_call_id"]]["status"] == "failed"
    assert results[good["client_call_id"]]["status"] == "created"


# --- What ingest computes ---------------------------------------------------


async def test_ingest_writes_all_three_timestamps_and_the_skew(
    db, installation_factory, device_client_factory
) -> None:
    """N36: device time is data, server receipt is truth, skew is evidence."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    body = (await _post(client)).json()
    call = await db.get(CallModel, uuid.UUID(body["results"][0]["id"]))

    assert call.started_at == STARTED_AT
    assert call.device_epoch_ms == int(STARTED_AT.timestamp() * 1000)
    assert call.device_timezone == "Asia/Tashkent"
    assert call.received_at > call.started_at
    # The fixture's device clock is years behind, so the skew is large and
    # positive — the point is that it is computed and stored, not guessed.
    assert call.clock_skew_sec != 0


async def test_the_number_comes_from_the_installation_not_the_payload(
    db, installation_factory, device_client_factory
) -> None:
    """SPEC §4.4 rule 2. There is no field for it, and that is the design."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    body = (await _post(client)).json()
    call = await db.get(CallModel, uuid.UUID(body["results"][0]["id"]))
    assert call.number_id == installation.number_id
    assert call.agent_id == installation.agent_id


async def test_attribution_uses_the_assignment_covering_started_at(
    db, agent_factory, registered_number_factory, installation_factory,
    device_client_factory, user_factory
) -> None:
    """D-08: a call made before a handover stays with the agent who made it.

    This is the whole reason ``number_assignments`` is time-boxed rather than a
    column on the agent, and it is T31's done criterion.
    """
    from src.core.enums import UserRole
    from src.modules.numbers.models import NumberAssignmentModel

    admin_user = await user_factory(UserRole.ADMIN)
    first = await agent_factory(full_name="Agent A")
    second = await agent_factory(full_name="Agent B")
    handover = STARTED_AT + timedelta(days=1)

    number = await registered_number_factory()
    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=first.id,
            valid_from=STARTED_AT - timedelta(days=30),
            valid_to=handover,
            created_by=admin_user.id,
        )
    )
    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=second.id,
            valid_from=handover,
            created_by=admin_user.id,
        )
    )
    await db.flush()

    installation = await installation_factory(agent=second, number=number)
    client = await device_client_factory(installation)

    old_call = (await _post(client)).json()["results"][0]
    new_call = (
        await _post(
            client,
            started_at=(handover + timedelta(hours=2)).isoformat(),
            answered_at=(handover + timedelta(hours=2, seconds=5)).isoformat(),
            ended_at=(handover + timedelta(hours=2, seconds=100)).isoformat(),
            duration_sec=95,
        )
    ).json()["results"][0]

    assert (await db.get(CallModel, uuid.UUID(old_call["id"]))).agent_id == first.id
    assert (await db.get(CallModel, uuid.UUID(new_call["id"]))).agent_id == second.id


async def test_a_call_outside_every_assignment_is_kept_and_alerted(
    db, installation_factory, device_client_factory
) -> None:
    """Dropping the call would be worse than attributing it imperfectly."""
    from src.core.enums import AlertKind
    from src.modules.alerts.models import AlertModel

    installation = await installation_factory()
    client = await device_client_factory(installation)
    ancient = datetime(2020, 1, 1, 10, tzinfo=UTC)
    body = (
        await _post(
            client,
            started_at=ancient.isoformat(),
            answered_at=(ancient + timedelta(seconds=5)).isoformat(),
            ended_at=(ancient + timedelta(seconds=60)).isoformat(),
            duration_sec=55,
        )
    ).json()
    assert body["results"][0]["status"] == "created"
    alerts = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AlertModel)
        .where(AlertModel.kind == AlertKind.ATTRIBUTION_OUT_OF_RANGE)
    )
    assert alerts == 1


async def test_unanswered_call_is_not_expected_to_have_audio(
    db, installation_factory, device_client_factory
) -> None:
    installation = await installation_factory()
    client = await device_client_factory(installation)
    body = (
        await _post(
            client,
            disposition="no_answer",
            answered_at=None,
            duration_sec=0,
            audio_expected=False,
        )
    ).json()
    assert body["results"][0]["audio_upload"] == "not_expected"
    call = await db.get(CallModel, uuid.UUID(body["results"][0]["id"]))
    assert call.audio_missing_reason is AudioMissingReason.NOT_EXPECTED


async def test_call_type_is_internal_for_a_registered_number(
    db, installation_factory, device_client_factory, registered_number_factory,
    agent_factory
) -> None:
    """UC-25: a colleague's work number is internal, computed at ingest."""
    colleague = await agent_factory()
    colleague_number = await registered_number_factory(
        agent=colleague, e164="+998907776655"
    )
    installation = await installation_factory()
    client = await device_client_factory(installation)
    body = (await _post(client, remote_number=colleague_number.e164)).json()
    call = await db.get(CallModel, uuid.UUID(body["results"][0]["id"]))
    assert call.call_type is CallType.INTERNAL


async def test_an_unparseable_number_is_stored_raw_with_a_null_key(
    db, installation_factory, device_client_factory
) -> None:
    """Losing a call because its number was odd is the worse failure."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    body = (await _post(client, remote_number="1234")).json()
    call = await db.get(CallModel, uuid.UUID(body["results"][0]["id"]))
    await db.refresh(call)
    assert call.remote_number == "1234"
    assert call.remote_number_key is None


# --- Device authentication --------------------------------------------------


async def test_ingest_without_a_token_is_401(client) -> None:
    response = await client.post("/api/device/v1/calls", json={"calls": [call_payload()]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_a_missing_required_header_is_400_not_500(
    installation_factory, device_client_factory
) -> None:
    """SPEC §4 rule 5: naming the header the app forgot."""
    installation = await installation_factory()
    client = await device_client_factory(installation)
    del client.headers["X-App-Version"]
    response = await client.post(
        "/api/device/v1/calls", json={"calls": [call_payload()]}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "header_missing"
    assert "X-App-Version" in response.json()["error"]["detail"]["headers"]


async def test_a_token_used_from_another_installation_is_refused(
    installation_factory, device_client_factory
) -> None:
    """N24: a copied token is rejected on first use."""
    installation = await installation_factory()
    client = await device_client_factory(
        installation, **{"X-Installation-Id": str(uuid.uuid4())}
    )
    response = await client.post(
        "/api/device/v1/calls", json={"calls": [call_payload()]}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "installation_mismatch"


async def test_an_unverified_installation_cannot_upload_a_call(
    installation_factory, device_client_factory
) -> None:
    """The privacy boundary starts at enrolment, not at the first POST /calls."""
    installation = await installation_factory(status=InstallationStatus.PENDING)
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/calls", json={"calls": [call_payload()]}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "verification_required"


async def test_a_replaced_installation_still_drains_its_queue(
    installation_factory, device_client_factory
) -> None:
    """UC-07/SPEC §9.3: refusing an old binding must never destroy data."""
    installation = await installation_factory(status=InstallationStatus.REPLACED)
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/calls", json={"calls": [call_payload()]}
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "created"


async def test_a_revoked_installation_is_refused(
    installation_factory, device_client_factory
) -> None:
    installation = await installation_factory(status=InstallationStatus.REVOKED)
    client = await device_client_factory(installation)
    response = await client.post(
        "/api/device/v1/calls", json={"calls": [call_payload()]}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "installation_revoked"


# --- The panel list ---------------------------------------------------------


async def test_manager_sees_every_call(manager, call_factory) -> None:
    await call_factory()
    await call_factory()
    response = await manager.get("/api/v1/calls")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


async def test_sales_sees_only_their_own_calls(
    db, sales, call_factory, installation_factory, agent_factory
) -> None:
    """UC-21, and the reason ``users.agent_id`` has a CHECK behind it."""
    from src.modules.agents.models import AgentModel

    own_agent = await db.get(AgentModel, sales.principal.agent_id)
    own_installation = await installation_factory(agent=own_agent)
    mine = await call_factory(installation=own_installation)
    theirs = await call_factory()

    body = (await sales.get("/api/v1/calls")).json()
    ids = {item["id"] for item in body["items"]}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids


async def test_another_agents_call_is_404_not_403(sales, call_factory) -> None:
    """403 would confirm the row exists, which is the leak (SPEC §4.1 rule 2)."""
    other = await call_factory()
    response = await sales.get(f"/api/v1/calls/{other.id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "call_not_found"


async def test_viewer_cannot_read_calls_at_all(viewer, call_factory) -> None:
    await call_factory()
    response = await viewer.get("/api/v1/calls")
    assert response.status_code == 403


async def test_listing_without_a_token_is_401(client, call_factory) -> None:
    await call_factory()
    assert (await client.get("/api/v1/calls")).status_code == 401


async def test_the_cursor_pages_without_skipping_or_repeating(
    manager, call_factory
) -> None:
    """UC-19's guarantee: keyset paging, ordered on server receipt time."""
    created = [await call_factory() for _ in range(5)]
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        url = "/api/v1/calls?limit=2" + (f"&cursor={cursor}" if cursor else "")
        body = (await manager.get(url)).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            break
    assert len(seen) == len(set(seen)) == len(created)


async def test_ordering_is_on_received_at_not_a_device_timestamp(
    manager, call_factory
) -> None:
    """N36: devices lie about time, so the server's receipt orders the list."""
    old_device_clock = await call_factory(
        started_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    newer_receipt = await call_factory(started_at=datetime(2020, 1, 1, tzinfo=UTC))
    body = (await manager.get("/api/v1/calls")).json()
    assert [item["id"] for item in body["items"]][:2] == [
        str(newer_receipt.id),
        str(old_device_clock.id),
    ]


async def test_with_total_counts_the_filtered_set(manager, call_factory) -> None:
    await call_factory()
    await call_factory(disposition=CallDisposition.NO_ANSWER)
    body = (await manager.get("/api/v1/calls?with_total=true")).json()
    assert body["total"] == 2
    assert (await manager.get("/api/v1/calls")).json()["total"] is None


async def test_a_tampered_cursor_is_400_not_500(manager) -> None:
    """Silently restarting from page one is how an export duplicates rows."""
    response = await manager.get("/api/v1/calls?cursor=not-a-cursor")
    assert response.status_code == 400


# --- The no-delete policy ---------------------------------------------------


async def test_delete_is_405_for_every_role(
    admin, manager, sales, viewer, call_factory
) -> None:
    """UC-26/T45: nobody deletes a call or its audio, including an admin.

    Otherwise the first bad call gets quietly removed and the dataset is worth
    nothing. Only the retention job deletes audio, and it never deletes a call.

    The four clients are taken as fixtures rather than through
    ``getfixturevalue``: resolving an async fixture from inside a running test
    re-enters the event loop.
    """
    call = await call_factory()
    for role, http_client in (
        ("admin", admin), ("manager", manager), ("sales", sales), ("viewer", viewer)
    ):
        for path in (f"/api/v1/calls/{call.id}", f"/api/v1/calls/{call.id}/audio"):
            response = await http_client.delete(path)
            assert response.status_code == 405, (role, path)
            assert response.json()["error"]["code"] == "delete_not_allowed"


# --- Filters, export and reclassification (T46, T48, T49) -------------------


async def test_filters_narrow_the_list(manager, call_factory) -> None:
    await call_factory(direction=CallDirection.OUTGOING)
    await call_factory(
        direction=CallDirection.INCOMING, disposition=CallDisposition.MISSED
    )
    body = (await manager.get("/api/v1/calls?direction=incoming")).json()
    assert body["items"] and all(i["direction"] == "incoming" for i in body["items"])


async def test_the_remote_number_filter_matches_on_the_key(
    manager, call_factory
) -> None:
    """N37: any format of a number finds the same calls."""
    await call_factory(remote_number="+998935554433")
    await call_factory(remote_number="+998901112299")
    for typed in ("+998 93 555-44-33", "935554433", "8 93 555 44 33"):
        body = (await manager.get(f"/api/v1/calls?remote_number={typed}")).json()
        assert len(body["items"]) == 1, typed


async def test_the_date_filter_uses_the_call_not_the_upload(
    manager, call_factory
) -> None:
    """D-08: a call made yesterday and uploaded today belongs to yesterday."""
    old = await call_factory(started_at=datetime(2026, 3, 1, 10, tzinfo=UTC))
    await call_factory(started_at=datetime(2026, 8, 1, 10, tzinfo=UTC))
    body = (
        await manager.get("/api/v1/calls?date_from=2026-03-01&date_to=2026-03-01")
    ).json()
    assert [i["id"] for i in body["items"]] == [str(old.id)]


async def test_the_contact_search_escapes_metacharacters(manager, call_factory) -> None:
    await call_factory(contact_name="Anvar")
    await call_factory(contact_name="100% Bonus")
    body = (await manager.get("/api/v1/calls?q=%25")).json()
    assert [i["contact_name"] for i in body["items"]] == ["100% Bonus"]


async def test_the_export_row_count_equals_the_filtered_total(
    manager, call_factory
) -> None:
    """UC-22's acceptance criterion. One filter builder produces both."""
    for _ in range(3):
        await call_factory(direction=CallDirection.OUTGOING)
    await call_factory(direction=CallDirection.INCOMING, disposition=CallDisposition.MISSED)

    listed = (await manager.get("/api/v1/calls?direction=outgoing&with_total=true")).json()
    export = await manager.get("/api/v1/calls/export?direction=outgoing")
    assert export.status_code == 200
    data_rows = [line for line in export.text.strip().split("\r\n")[1:] if line]
    assert len(data_rows) == listed["total"] == 3


async def test_the_export_is_excel_readable_in_a_uz_locale(
    manager, call_factory
) -> None:
    """UTF-8 with a BOM and a ``;`` delimiter, or Excel renders one column and
    the person who opened it has no way to know."""
    await call_factory(contact_name="Anvar do'kon")
    export = await manager.get("/api/v1/calls/export")
    assert export.text.startswith("﻿")
    header = export.text.split("\r\n")[0].lstrip("﻿")
    assert ";" in header and "," not in header


async def test_a_sales_export_carries_only_their_own_rows(
    db, sales, call_factory, installation_factory
) -> None:
    from src.modules.agents.models import AgentModel

    own_agent = await db.get(AgentModel, sales.principal.agent_id)
    mine = await call_factory(installation=await installation_factory(agent=own_agent))
    await call_factory()
    # `sales` holds no reports:export, so the route is closed to them entirely —
    # which is the stronger answer, and the scoped query backs it up.
    assert (await sales.get("/api/v1/calls/export")).status_code == 403
    listed = (await sales.get("/api/v1/calls")).json()
    assert [i["id"] for i in listed["items"]] == [str(mine.id)]


async def test_adding_a_suffix_rule_reclassifies_existing_calls(
    db, admin, call_factory
) -> None:
    """UC-25: a number that is internal today was internal yesterday too."""
    # The factory writes the row directly, so call_type is the column default;
    # the classifier runs at ingest and, here, in the reclassify below.
    call = await call_factory(remote_number="+998712345700")

    response = await admin.post(
        "/api/v1/line-directory", json={"pattern": "700", "kind": "suffix"}
    )
    assert response.status_code == 201
    assert response.json()["calls_reclassified"] >= 1
    await db.refresh(call)
    assert call.call_type is CallType.INTERNAL


async def test_removing_a_rule_reclassifies_back(db, admin, call_factory) -> None:
    call = await call_factory(remote_number="+998712345700")
    created = await admin.post(
        "/api/v1/line-directory", json={"pattern": "700", "kind": "suffix"}
    )
    entry_id = created.json()["entry"]["id"]
    await admin.delete(f"/api/v1/line-directory/{entry_id}")
    await db.refresh(call)
    assert call.call_type is CallType.EXTERNAL


async def test_only_settings_write_may_edit_the_directory(manager, sales) -> None:
    body = {"pattern": "700", "kind": "suffix"}
    assert (await manager.post("/api/v1/line-directory", json=body)).status_code == 403
    assert (await sales.get("/api/v1/line-directory")).status_code == 403


# --- Display fields, the audio sub-object and sorting -----------------------


async def test_the_list_carries_display_fields_not_only_ids(
    db, manager, call_factory, installation_factory, agent_factory,
    registered_number_factory, device_factory
) -> None:
    """Making the browser resolve a name per row is N+1 relocated, not solved."""
    agent = await agent_factory(full_name="Aziz Karimov")
    number = await registered_number_factory(agent=agent, e164="+998901112233")
    device = await device_factory(manufacturer="Xiaomi", model="Redmi Note 12")
    installation = await installation_factory(agent=agent, number=number, device=device)
    await call_factory(installation=installation)

    item = (await manager.get("/api/v1/calls")).json()["items"][0]
    assert item["agent_name"] == "Aziz Karimov"
    assert item["number_e164"] == "+998901112233"
    assert item["device_model"] == "Xiaomi Redmi Note 12", (
        "the device_model filter exists server-side; the column has to exist too"
    )


async def test_the_call_carries_its_capture_route(
    db, manager, audio_factory
) -> None:
    """S1: app_voice_recognition and app_mic must stay distinguishable.

    The per-model capture rate is the M0 baseline and UC-23's regression alert
    reads it; collapsing the routes into "audio: yes/no" would make "which
    mechanism works on this handset" unanswerable.
    """
    from src.core.enums import CaptureRoute

    audio = await audio_factory(
        payload=b"OggS" + b"\x00" * 64,
        capture_route=CaptureRoute.APP_VOICE_RECOGNITION,
        capture_route_detail="VOICE_RECOGNITION",
        duration_ms=120_000,
    )
    item = (await manager.get(f"/api/v1/calls/{audio.call_id}")).json()
    assert item["audio"]["available"] is True
    assert item["audio"]["capture_route"] == "app_voice_recognition"
    assert item["audio"]["capture_route_detail"] == "VOICE_RECOGNITION"
    assert item["audio"]["duration_ms"] == 120_000


async def test_a_call_without_audio_says_why_in_the_same_shape(
    manager, call_factory
) -> None:
    """The panel renders one component either way, and it needs the reason."""
    call = await call_factory(audio_missing_reason=AudioMissingReason.NO_PERMISSION)
    item = (await manager.get(f"/api/v1/calls/{call.id}")).json()
    assert item["audio"]["available"] is False
    assert item["audio"]["audio_missing_reason"] == "no_permission"
    assert item["audio"]["capture_route"] is None


async def test_expired_audio_is_marked_unavailable(db, manager, audio_factory) -> None:
    from src.modules.audio.service import AudioService

    audio = await audio_factory(payload=b"OggS")
    audio.recorded_at = datetime(2020, 1, 1, tzinfo=UTC)
    await db.flush()
    await AudioService(db).apply_retention()

    item = (await manager.get(f"/api/v1/calls/{audio.call_id}")).json()
    assert item["audio"]["available"] is False
    assert item["audio"]["expired_at"] is not None


async def test_sorting_by_duration_is_stable(manager, call_factory) -> None:
    """SPEC §4.7 offers it, and duration values tie constantly — so the sort
    pairs with ``id`` or paging repeats rows."""
    for duration in (30, 30, 600, 5):
        await call_factory(duration_sec=duration)
    body = (await manager.get("/api/v1/calls?sort=duration_sec&order=desc")).json()
    assert [i["duration_sec"] for i in body["items"]] == [600, 30, 30, 5]

    seen: list[str] = []
    cursor = None
    for _ in range(4):
        url = "/api/v1/calls?sort=duration_sec&order=desc&limit=2"
        page = (await manager.get(url + (f"&cursor={cursor}" if cursor else ""))).json()
        seen.extend(i["id"] for i in page["items"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert len(seen) == len(set(seen)) == 4


async def test_sorting_ascending_by_started_at(manager, call_factory) -> None:
    early = await call_factory(started_at=datetime(2026, 1, 1, tzinfo=UTC))
    late = await call_factory(started_at=datetime(2026, 8, 1, tzinfo=UTC))
    body = (await manager.get("/api/v1/calls?sort=started_at&order=asc")).json()
    assert [i["id"] for i in body["items"]] == [str(early.id), str(late.id)]


async def test_an_unknown_sort_is_refused(manager) -> None:
    assert (await manager.get("/api/v1/calls?sort=note")).status_code == 422
