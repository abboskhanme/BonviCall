"""Sales control over the wire: access, the upload gate, and the ten routes.

═══ WHY THE ACCESS TESTS COME FIRST ════════════════════════════════════════
This list is a check carried out ON an employee. A salesperson who can see that
their own sale has been flagged has the chance to prepare before the check —
which is the one thing the queue must not allow. BonviZvonki says so in its own
router docstring, and here it is asserted rather than described.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.modules.sales.models import SaleBranchModel, SalePartnerModel, SaleReviewModel
from src.modules.sales.rules import ClientKind, ReviewState, Verdict
from src.modules.sales.tests.conftest import SALE_DAY
from src.modules.sales.tests.test_sales_import import (
    catalog,
    catalog_row,
    register,
    sale_row,
)

pytestmark = pytest.mark.asyncio

SALES = "/api/v1/sales"
COMPLIANCE = f"{SALES}/compliance"
NOON = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Every route, with the method and a body that is valid enough to get past
#: FastAPI's own validation. The RBAC tests are parameterised over this so a
#: new route cannot be added without an access case (CONVENTIONS.md §11, T20).
NIL = "00000000-0000-0000-0000-000000000000"

READ_ROUTES = [
    ("GET", COMPLIANCE),
    ("GET", f"{COMPLIANCE}/summary"),
    ("GET", f"{COMPLIANCE}/timeline"),
    ("GET", f"{SALES}/branches"),
]

WRITE_ROUTES = [
    ("PUT", f"{SALES}/branches/Buxoro", {"agent_id": None}),
    ("PUT", f"{SALES}/partners/%D0%9A80001/exclusion", {"excluded": True}),
    ("POST", f"{SALES}/digest/test", None),
]

REVIEW_ROUTE = ("POST", f"{SALES}/{NIL}/review", {"status": "justified"})


def _upload(payload: bytes, name: str = "savdo kunlik.xlsx", content_type: str = XLSX):
    return {"file": (name, payload, content_type)}


async def _send(client, method: str, path: str, body=None):
    if method == "GET":
        return await client.get(path)
    if method == "PUT":
        return await client.put(path, json=body)
    return await client.post(path, json=body) if body else await client.post(path)


# ══════════════════════════════════════════════════════════════
#  Access
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("method", "path"), READ_ROUTES)
async def test_anonymous_is_401(client, method, path) -> None:
    assert (await _send(client, method, path)).status_code == 401


@pytest.mark.parametrize(("method", "path"), READ_ROUTES)
async def test_a_manager_may_read_the_report(manager, method, path) -> None:
    assert (await _send(manager, method, path)).status_code == 200


@pytest.mark.parametrize(("method", "path"), READ_ROUTES)
async def test_a_salesperson_may_read_nothing(sales, method, path) -> None:
    """⚠️ NOT AN OVERSIGHT — the point. The registry grants a salesperson no
    ``reports:*`` at all, so the shape already fits: every report on this
    surface is fleet-wide, and this one is a check ON them.
    """
    assert (await _send(sales, method, path)).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), WRITE_ROUTES)
async def test_a_manager_may_not_change_how_the_system_behaves(
    manager, method, path, body
) -> None:
    """Running an import rewrites the register every later number is computed
    from, and excluding a branch changes which sales are checked at all. Both
    are ``settings:write``, which this registry already draws as that line."""
    assert (await _send(manager, method, path, body)).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), WRITE_ROUTES)
async def test_anonymous_cannot_write_either(client, method, path, body) -> None:
    assert (await _send(client, method, path, body)).status_code == 401


async def test_importing_needs_the_write_permission(manager, sales) -> None:
    payload = register(sale_row())
    for surface in (manager, sales):
        for path in (f"{SALES}/import", f"{SALES}/import/preview"):
            response = await surface.post(path, files=_upload(payload))
            assert response.status_code == 403, path


async def test_a_manager_may_record_a_decision(manager) -> None:
    """``calls:note`` — the closest existing constant for "a human writes a
    judgement onto a record", and the one BOTH roles that work this queue hold.
    A 404 here means the permission passed and the sale simply does not exist.
    """
    response = await manager.post(f"{SALES}/{NIL}/review", json={"status": "justified"})
    assert response.status_code == 404


async def test_a_salesperson_may_not_record_a_decision(sales) -> None:
    response = await sales.post(f"{SALES}/{NIL}/review", json={"status": "justified"})
    assert response.status_code == 403


# ══════════════════════════════════════════════════════════════
#  The upload gate
# ══════════════════════════════════════════════════════════════


async def test_only_xlsx_is_accepted(admin) -> None:
    """⚠️ ``.xls`` and ``.csv`` are refused DELIBERATELY: openpyxl cannot read
    them and the failure would be unintelligible ("File is not a zip file").
    SAP exports both as ``.xlsx``, so nothing is lost."""
    response = await admin.post(
        f"{SALES}/import", files=_upload(b"a,b,c", name="savdo.csv", content_type="text/csv")
    )
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"] == "not_xlsx"


async def test_a_wrong_content_type_is_refused_before_the_bytes_are_parsed(
    admin,
) -> None:
    response = await admin.post(
        f"{SALES}/import",
        files=_upload(register(sale_row()), content_type="text/csv"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"] == "wrong_content_type"


async def test_an_empty_file_is_refused(admin) -> None:
    response = await admin.post(f"{SALES}/import", files=_upload(b""))
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"] == "empty_file"


async def test_an_oversized_upload_is_413(admin, monkeypatch) -> None:
    """A ceiling MUST exist — openpyxl opens the file into memory."""
    from src.api.panel import sales as router

    monkeypatch.setattr(router, "MAX_UPLOAD_BYTES", 16)
    response = await admin.post(f"{SALES}/import", files=_upload(register(sale_row())))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


# ══════════════════════════════════════════════════════════════
#  Import, end to end
# ══════════════════════════════════════════════════════════════


async def test_the_estimate_then_the_import(admin, db) -> None:
    """Two stages: a one-stage import put the wrong file into the database
    silently and there was no way back."""
    payload = register(sale_row())

    preview = await admin.post(f"{SALES}/import/preview", files=_upload(payload))
    assert preview.status_code == 200
    body = preview.json()
    assert body["kind"] == "register"
    assert (body["new_rows"], body["existing_rows"]) == (1, 0)

    report = await admin.post(f"{SALES}/import", files=_upload(payload))
    assert report.status_code == 200
    assert report.json()["created"] == 1

    # And the estimate now says the same file would add nothing.
    again = await admin.post(f"{SALES}/import/preview", files=_upload(payload))
    assert again.json() == {**body, "new_rows": 0, "existing_rows": 1}


async def test_the_import_report_names_the_unlinked_branches(admin) -> None:
    response = await admin.post(
        f"{SALES}/import", files=_upload(register(sale_row(branch="Логистика")))
    )
    assert response.json()["unmatched_branches"] == ["Логистика"]


# ══════════════════════════════════════════════════════════════
#  The queue
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def world(partner_factory, sale_factory, call_factory, installation_factory, agent_factory):
    """A clean sale, a suspicious one, and one that cannot be checked."""

    async def _build():
        agent = await agent_factory(full_name="Aziz")
        installation = await installation_factory(agent=agent)
        clean = await partner_factory(code="К80011", name="Toza mijoz")
        dirty = await partner_factory(code="К80022", name="Shubhali mijoz")
        blind = await partner_factory(code="К80033", phone="(99) 999-99-99")
        await sale_factory(partner=clean, external_id="OP-CLEAN")
        suspicious = await sale_factory(
            partner=dirty, external_id="OP-DIRTY", amount_usd=Decimal("5610")
        )
        await sale_factory(partner=blind, external_id="OP-BLIND")
        await call_factory(
            installation=installation, remote_number=clean.phone, started_at=NOON
        )
        return {"agent": agent, "suspicious": suspicious}

    return _build


def _window() -> dict[str, str]:
    return {"date_from": SALE_DAY.isoformat(), "date_to": SALE_DAY.isoformat()}


async def test_the_queue_answers_with_the_verdict_and_its_evidence(
    admin, world
) -> None:
    """The evidence fields are a REQUIREMENT: the manager re-derives the number
    by hand, and without "when was the last conversation" the list is not
    believed."""
    await world()
    body = (
        await admin.get(
            COMPLIANCE, params={**_window(), "review": ReviewState.ALL.value}
        )
    ).json()

    rows = {row["external_id"]: row for row in body["items"]}
    assert set(rows) == {"OP-CLEAN", "OP-DIRTY", "OP-BLIND"}
    assert rows["OP-CLEAN"]["verdict"] == Verdict.OK.value
    assert rows["OP-CLEAN"]["days_before"] == 0
    assert rows["OP-CLEAN"]["last_call_id"] is not None, "the panel can open it"
    assert rows["OP-DIRTY"]["broken_rules"] == ["R1", "R3"]
    assert rows["OP-BLIND"]["skip_reason"] == "no_phone"
    assert body["window_days"] == 3, "which window produced these verdicts"


async def test_the_queue_is_cursor_paged_and_never_repeats_a_row(
    admin, world
) -> None:
    """⚠️ An ``OFFSET`` is wrong for THIS list: deciding on a sale removes it
    from the default set, every later page shifts by one, and a sale is never
    seen at all."""
    await world()
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params = {**_window(), "review": ReviewState.ALL.value, "limit": 1}
        if cursor:
            params["cursor"] = cursor
        body = (await admin.get(COMPLIANCE, params=params)).json()
        seen += [row["external_id"] for row in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == ["OP-BLIND", "OP-CLEAN", "OP-DIRTY"]
    assert len(seen) == len(set(seen)), "no row twice"


async def test_the_total_is_only_computed_when_asked(admin, world) -> None:
    await world()
    params = {**_window(), "review": ReviewState.ALL.value}
    assert (await admin.get(COMPLIANCE, params=params)).json()["total"] is None
    assert (
        await admin.get(COMPLIANCE, params={**params, "with_total": True})
    ).json()["total"] == 3


async def test_the_default_queue_hides_decided_sales(admin, db, world) -> None:
    built = await world()
    response = await admin.post(
        f"{SALES}/{built['suspicious'].id}/review",
        json={"status": "justified", "reason": "walk_in", "note": "Kelib oldi"},
    )
    assert response.status_code == 200
    assert response.json()["reviewed_by"] is not None, "a decision is never anonymous"

    body = (await admin.get(COMPLIANCE, params=_window())).json()
    assert "OP-DIRTY" not in {row["external_id"] for row in body["items"]}

    archive = (
        await admin.get(
            COMPLIANCE, params={**_window(), "review": ReviewState.JUSTIFIED.value}
        )
    ).json()
    assert [row["external_id"] for row in archive["items"]] == ["OP-DIRTY"]


async def test_a_reason_is_refused_on_a_confirmed_suspicion(admin, world) -> None:
    """⚠️ Refused rather than silently dropped. The reason list explains a
    JUSTIFICATION; a field that looks accepted and is not is how a panel ships
    a dead control — which is what BonviZvonki does here."""
    built = await world()
    response = await admin.post(
        f"{SALES}/{built['suspicious'].id}/review",
        json={"status": "confirmed", "reason": "walk_in"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["field"] == "reason"


async def test_changing_your_mind_overwrites_rather_than_adding_a_row(
    admin, db, world
) -> None:
    built = await world()
    sale_id = built["suspicious"].id
    await admin.post(f"{SALES}/{sale_id}/review", json={"status": "justified"})
    await admin.post(f"{SALES}/{sale_id}/review", json={"status": "confirmed"})

    rows = (
        (await db.execute(select(SaleReviewModel).where(SaleReviewModel.sale_id == sale_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "confirmed"


async def test_the_summary_keeps_all_three_cards(admin, world) -> None:
    await world()
    body = (await admin.get(f"{COMPLIANCE}/summary", params=_window())).json()
    assert (body["total"], body["ok"], body["suspicious"], body["not_checkable"]) == (
        3,
        1,
        1,
        1,
    )
    assert body["window_days"] == 3


async def test_the_walk_in_section_reports_its_own_measure(
    admin, partner_factory, sale_factory
) -> None:
    partner = await partner_factory(code="К00001")
    await sale_factory(partner=partner, amount_usd=Decimal("5000"))

    body = (
        await admin.get(
            f"{COMPLIANCE}/summary",
            params={**_window(), "client_kind": ClientKind.WALK_IN.value},
        )
    ).json()
    assert body["over_limit"] == 1
    assert body["walk_in_limit"] == 2000, "stated, not implied"
    assert body["over_limit_amount"] == 5000.0


# ══════════════════════════════════════════════════════════════
#  The customer timeline
# ══════════════════════════════════════════════════════════════


async def test_the_timeline_puts_the_conversation_before_the_sale(
    admin, world
) -> None:
    """⚠️ A sale has no time and the rules read a same-day conversation as
    having come FIRST. The chain has to show that reading, or the screen prints
    "sold first, then talked"."""
    await world()
    body = (
        await admin.get(
            f"{COMPLIANCE}/timeline",
            params={**_window(), "only_suspicious": "false"},
        )
    ).json()

    clean = next(c for c in body["clients"] if c["partner_code"] == "К80011")
    assert [event["kind"] for event in clean["events"]] == ["call", "sale"]
    assert clean["calls_count"] == 1
    assert clean["events"][0]["has_audio"] is False


async def test_the_timeline_selects_customers_not_sales(admin, world) -> None:
    """⚠️ ``only_suspicious`` works at CUSTOMER level: a suspicious customer's
    CLEAN sales stay in the chain, or the sequence would read as "every sale to
    this customer was suspicious".

    ⚠️ And ``not_checkable`` IS NOT SUSPICIOUS — К80033 has a fabricated number
    and no rule is claimed against it, so it is not in a list of customers to
    look at. It is still a number on the report's third card, which is where
    "SAP's data is poor" belongs.
    """
    await world()
    body = (
        await admin.get(f"{COMPLIANCE}/timeline", params=_window())
    ).json()
    assert {c["partner_code"] for c in body["clients"]} == {"К80022"}

    everyone = (
        await admin.get(
            f"{COMPLIANCE}/timeline", params={**_window(), "only_suspicious": "false"}
        )
    ).json()
    assert {c["partner_code"] for c in everyone["clients"]} == {
        "К80011",
        "К80022",
        "К80033",
    }


async def test_the_timeline_says_when_it_was_cut(admin, world) -> None:
    await world()
    body = (
        await admin.get(
            f"{COMPLIANCE}/timeline",
            params={**_window(), "only_suspicious": "false", "max_clients": 1},
        )
    ).json()
    assert body["truncated"] is True
    assert len(body["clients"]) == 1


# ══════════════════════════════════════════════════════════════
#  The branch map and the exclusions
# ══════════════════════════════════════════════════════════════


async def test_the_map_lists_unlinked_branches_with_their_sale_counts(
    admin, db
) -> None:
    """The manager should link the branch with the most sales behind it first."""
    await admin.post(
        f"{SALES}/import",
        files=_upload(
            register(
                sale_row("OP-1", branch="Бухоро"),
                sale_row("OP-2", branch="Бухоро"),
                sale_row("OP-3", branch="Логистика"),
            )
        ),
    )
    body = (await admin.get(f"{SALES}/branches")).json()
    assert body["total"] == 2
    assert [row["branch"] for row in body["items"]] == ["Бухоро", "Логистика"]
    assert body["items"][0]["sales"] == 2
    assert body["items"][0]["agent_id"] is None


async def test_linking_an_employee_moves_the_existing_sales(
    admin, db, agent_factory
) -> None:
    """⚠️ A backfill alone is NOT enough: it fills only an EMPTY agent, so
    correcting a wrong link would leave the old sales on the old employee and
    the report would be a lie."""
    await admin.post(
        f"{SALES}/import", files=_upload(register(sale_row("OP-1", branch="Бухоро")))
    )
    agent = await agent_factory(full_name="Yangi xodim")

    response = await admin.put(
        f"{SALES}/branches/%D0%91%D1%83%D1%85%D0%BE%D1%80%D0%BE",
        json={"agent_id": str(agent.id)},
    )
    assert response.status_code == 200
    assert response.json()["agent_name"] == "Yangi xodim"
    assert response.json()["matched_automatically"] is False

    row = await db.get(SaleBranchModel, "Бухоро")
    await db.refresh(row)
    assert row.assigned_at is not None, "hands off, import"


async def test_excluding_a_branch_alone_does_not_unlink_its_employee(
    admin, db, agent_factory
) -> None:
    """⚠️ ``agent_id: null`` is a full value ("unlink"); "not sent" is different.
    Without the ``model_fields_set`` test a bare "just exclude it" request would
    quietly unlink the employee as well."""
    agent = await agent_factory(full_name="Бухоро")
    await admin.post(
        f"{SALES}/import", files=_upload(register(sale_row("OP-1", branch="Бухоро")))
    )
    path = f"{SALES}/branches/%D0%91%D1%83%D1%85%D0%BE%D1%80%D0%BE"

    body = (await admin.put(path, json={"excluded": True})).json()
    assert body["excluded"] is True
    assert body["agent_id"] == str(agent.id)
    assert body["sales"] == 1, "the sales were not deleted"


async def test_a_missing_branch_is_404(admin) -> None:
    response = await admin.put(f"{SALES}/branches/Yoq", json={"excluded": True})
    assert response.status_code == 404


async def test_excluding_a_customer_moves_their_sales_and_deletes_nothing(
    admin, db, partner_factory, sale_factory
) -> None:
    partner = await partner_factory(code="К80500", name="Ombor")
    await sale_factory(partner=partner, external_id="OP-INT")

    response = await admin.put(
        f"{SALES}/partners/%D0%9A80500/exclusion", json={"excluded": True}
    )
    assert response.status_code == 200
    assert response.json() == {
        "code": "К80500",
        "name": "Ombor",
        "excluded": True,
        "sales": 1,
    }, "the REAL count comes back — which is what proves nothing was deleted"

    main = (await admin.get(COMPLIANCE, params={**_window(), "review": "all"})).json()
    assert main["items"] == []
    out = (
        await admin.get(
            COMPLIANCE, params={**_window(), "review": "all", "out_of_scope": True}
        )
    ).json()
    assert [row["external_id"] for row in out["items"]] == ["OP-INT"]


async def test_putting_a_customer_back_needs_no_re_import(
    admin, partner_factory, sale_factory
) -> None:
    partner = await partner_factory(code="К80500")
    await sale_factory(partner=partner, external_id="OP-INT")
    path = f"{SALES}/partners/%D0%9A80500/exclusion"

    await admin.put(path, json={"excluded": True})
    await admin.put(path, json={"excluded": False})

    body = (await admin.get(COMPLIANCE, params={**_window(), "review": "all"})).json()
    assert [row["external_id"] for row in body["items"]] == ["OP-INT"]


async def test_a_code_typed_with_a_latin_letter_is_404_not_a_silent_success(
    admin, partner_factory
) -> None:
    """⚠️ The SAP code's К is CYRILLIC (U+041A). A Latin ``K`` must not quietly
    get "done" for an answer."""
    await partner_factory(code="К80500")
    response = await admin.put(f"{SALES}/partners/K80500/exclusion", json={"excluded": True})
    assert response.status_code == 404


# ══════════════════════════════════════════════════════════════
#  The catalogue reaches the queue
# ══════════════════════════════════════════════════════════════


async def test_a_sale_imported_before_its_catalogue_becomes_checkable(
    admin, db, call_factory, installation_factory, agent_factory
) -> None:
    """The order of imports is in the user's hands, and the failure would be
    SILENT: the whole day would read "could not be checked"."""
    await admin.post(f"{SALES}/import", files=_upload(register(sale_row())))
    body = (await admin.get(COMPLIANCE, params={**_window(), "review": "all"})).json()
    assert body["items"][0]["skip_reason"] == "no_phone"

    await admin.post(
        f"{SALES}/import",
        files=_upload(catalog(catalog_row()), name="Workbook3.xlsx"),
    )
    partner = await db.scalar(
        select(SalePartnerModel).where(SalePartnerModel.code == "К82711")
    )
    await call_factory(
        installation=await installation_factory(agent=await agent_factory()),
        remote_number=partner.phone,
        started_at=NOON - timedelta(days=1),
    )

    body = (await admin.get(COMPLIANCE, params={**_window(), "review": "all"})).json()
    assert body["items"][0]["verdict"] == Verdict.OK.value
    assert body["items"][0]["skip_reason"] is None
