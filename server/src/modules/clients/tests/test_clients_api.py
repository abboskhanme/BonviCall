"""The customer directory over the wire: access, scope, grouping, paging.

The four things that can make this page lie, and therefore the four things
asserted hardest:

  · one customer arriving in three number formats counted as three customers;
  · a salesperson reading a colleague's customers by pasting an ``agent_id``;
  · a SEARCH changing the totals it was only supposed to find;
  · a card that contradicts the row it was opened from.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.enums import CallDirection, CallDisposition, CallType
from src.modules.agents.models import AgentModel
from src.modules.contacts.models import ClientContactModel

pytestmark = pytest.mark.asyncio

CLIENTS = "/api/v1/clients"

#: A fixed instant inside every window a test asks for. Tashkent is UTC+5 with
#: no daylight saving, so 09:00Z is 14:00 local — the middle of a working day
#: whichever side of midnight the assertion is about.
NOON = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

#: One customer. Written three ways on purpose.
NUMBER = "+998901112233"
KEY = "901112233"


def _window() -> dict[str, str]:
    return {"date_from": "2026-08-20", "date_to": "2026-08-20"}


async def _own(db, installation_factory, agent_id):
    return await installation_factory(agent=await db.get(AgentModel, agent_id))


async def _call(call_factory, installation, **overrides):
    overrides.setdefault("started_at", NOON)
    overrides.setdefault("remote_number", NUMBER)
    return await call_factory(installation=installation, **overrides)


async def _incoming(call_factory, installation, **overrides):
    return await _call(
        call_factory,
        installation,
        direction=CallDirection.INCOMING,
        disposition=overrides.pop("disposition", CallDisposition.MISSED),
        **overrides,
    )


# ── Access ────────────────────────────────────────────────────


async def test_anonymous_is_401(client) -> None:
    assert (await client.get(CLIENTS)).status_code == 401
    assert (await client.get(f"{CLIENTS}/{KEY}")).status_code == 401
    assert (await client.get(f"{CLIENTS}/{KEY}/calls")).status_code == 401


async def test_a_manager_may_read_the_directory(manager) -> None:
    assert (await manager.get(CLIENTS)).status_code == 200


async def test_a_salesperson_may_read_the_directory(sales) -> None:
    """``calls:read:own`` passes the gate; the query narrows below."""
    assert (await sales.get(CLIENTS)).status_code == 200


# ── Own scope ─────────────────────────────────────────────────


async def test_a_salesperson_sees_only_their_own_customers(
    sales, db, call_factory, installation_factory, agent_factory
) -> None:
    mine = await _own(db, installation_factory, sales.principal.agent_id)
    colleague = await installation_factory(agent=await agent_factory(full_name="Boshqa"))
    await _call(call_factory, mine, remote_number="+998901112233")
    await _call(call_factory, colleague, remote_number="+998907778899")

    body = (await sales.get(CLIENTS, params=_window())).json()
    assert [row["phone_key"] for row in body["items"]] == ["901112233"]


async def test_a_salesperson_cannot_name_a_colleague(
    sales, call_factory, installation_factory, agent_factory
) -> None:
    """⚠️ The ``agent_id`` filter is IGNORED for own-scope, never merged.

    Merged, a pasted id would hand over the colleague's customers on the spot.
    """
    colleague = await agent_factory(full_name="Boshqa")
    installation = await installation_factory(agent=colleague)
    await _call(call_factory, installation)

    body = (
        await sales.get(
            CLIENTS, params={**_window(), "agent_id": str(colleague.id)}
        )
    ).json()
    assert body["items"] == []


async def test_a_colleagues_customer_card_is_404_and_not_403(
    sales, call_factory, installation_factory, agent_factory
) -> None:
    """A 403 would confirm that somebody spoke to that number (SPEC §4.1 rule 2)."""
    installation = await installation_factory(agent=await agent_factory())
    await _call(call_factory, installation)
    assert (await sales.get(f"{CLIENTS}/{KEY}")).status_code == 404


async def test_an_unknown_number_is_404(manager) -> None:
    """The same answer as "not yours", on purpose."""
    assert (await manager.get(f"{CLIENTS}/900000000")).status_code == 404


async def test_a_key_that_is_not_digits_is_400(manager) -> None:
    """``/clients/undefined`` gets a comprehensible answer, not an empty page."""
    assert (await manager.get(f"{CLIENTS}/undefined")).status_code == 400


# ── Grouping ──────────────────────────────────────────────────


async def test_one_customer_written_three_ways_is_one_row(
    manager, call_factory, installation_factory
) -> None:
    """⚠️ THE POINT OF THE KEY. The same person arrives as "+998 90 111-22-33",
    "998901112233" and "901112233"; grouped on anything but the last nine
    digits they are three customers and every figure on the page is wrong."""
    installation = await installation_factory()
    for written in ("+998 90 111-22-33", "998901112233", "901112233"):
        await _call(call_factory, installation, remote_number=written)

    body = (await manager.get(CLIENTS, params={**_window(), "with_total": "true"})).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["phone_key"] == KEY
    assert body["items"][0]["calls_total"] == 3
    assert body["total"] == 1


async def test_a_number_too_short_to_be_a_key_is_not_a_customer(
    manager, call_factory, installation_factory
) -> None:
    """N37: below nine digits the generated key is NULL on purpose, because a
    short value matches the tail of almost any number. The switchboard
    therefore cannot appear in a customer directory — which is the right trade,
    and a real difference from BonviZvonki (``clients/rules.py``)."""
    installation = await installation_factory()
    await _call(call_factory, installation, remote_number="700")
    body = (await manager.get(CLIENTS, params=_window())).json()
    assert body["items"] == []


async def test_missed_counts_rejected_with_missed(
    manager, call_factory, installation_factory
) -> None:
    """The SAME definition the activity report uses: the phone rang and there
    was no conversation. Two sections must not disagree about this."""
    installation = await installation_factory()
    await _incoming(call_factory, installation, disposition=CallDisposition.MISSED)
    await _incoming(call_factory, installation, disposition=CallDisposition.REJECTED)
    await _incoming(call_factory, installation, disposition=CallDisposition.ANSWERED)

    row = (await manager.get(CLIENTS, params=_window())).json()["items"][0]
    assert row["inbound"] == 3
    assert row["missed"] == 2
    assert row["missed_rate"] == pytest.approx(66.7)


async def test_internal_conversations_are_out_by_default(
    manager, call_factory, installation_factory
) -> None:
    """Talking to a colleague is not a customer."""
    installation = await installation_factory()
    await _call(call_factory, installation, call_type=CallType.INTERNAL)
    await _call(
        call_factory,
        installation,
        remote_number="+998907778899",
        call_type=CallType.EXTERNAL,
    )

    default = (await manager.get(CLIENTS, params=_window())).json()
    assert [row["phone_key"] for row in default["items"]] == ["907778899"]

    internal = (
        await manager.get(CLIENTS, params={**_window(), "scope": "internal"})
    ).json()
    assert [row["phone_key"] for row in internal["items"]] == [KEY]

    every = (await manager.get(CLIENTS, params={**_window(), "scope": "all"})).json()
    assert len(every["items"]) == 2


async def test_an_unclassified_call_is_still_a_customer(
    manager, call_factory, installation_factory
) -> None:
    """⚠️ ``unknown`` is not "not a customer", it is "not decided yet" — an
    empty line directory yields it (UC-25). Hiding those rows quietly would
    make the list incomplete, which is the failure nobody notices."""
    installation = await installation_factory()
    await _call(call_factory, installation, call_type=CallType.UNKNOWN)
    body = (await manager.get(CLIENTS, params=_window())).json()
    assert [row["phone_key"] for row in body["items"]] == [KEY]


# ── The name ──────────────────────────────────────────────────


async def test_the_uploaded_dictionary_names_the_customer(
    manager, db, call_factory, installation_factory
) -> None:
    """The handset's own resolution is the FALLBACK: it is whatever that one
    employee had in their phone, so the same customer reads differently on two
    salespeople's calls (L3)."""
    installation = await installation_factory()
    await _call(call_factory, installation, contact_name="Anvar do'kon")
    db.add(
        ClientContactModel(
            phone_key=KEY, code="К00150", name="Elyor aka", raw_name="K00150 Elyor aka"
        )
    )
    await db.flush()

    row = (await manager.get(CLIENTS, params=_window())).json()["items"][0]
    assert row["name"] == "Elyor aka"
    assert row["code"] == "К00150"


async def test_the_handset_name_is_used_when_the_dictionary_is_silent(
    manager, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await _call(call_factory, installation, contact_name="Anvar do'kon")
    row = (await manager.get(CLIENTS, params=_window())).json()["items"][0]
    assert row["name"] == "Anvar do'kon"
    assert row["code"] is None


async def test_a_private_contact_never_names_a_customer(
    manager, db, call_factory, installation_factory
) -> None:
    """⚠️ A private acquaintance's name must not surface in a company report,
    and a colleague is not a customer. The ROW still exists — only the name is
    withheld (``contacts.rules.NAMING_KINDS``)."""
    installation = await installation_factory()
    await _call(call_factory, installation, contact_name=None)
    db.add(
        ClientContactModel(
            phone_key=KEY, name="Shifokor", raw_name="Shifokor", kind="personal"
        )
    )
    await db.flush()

    row = (await manager.get(CLIENTS, params=_window())).json()["items"][0]
    assert row["name"] is None


# ── Searching ─────────────────────────────────────────────────


async def test_a_search_finds_a_customer_by_a_name_on_one_call_only(
    manager, call_factory, installation_factory
) -> None:
    """⚠️ AND DOES NOT CHANGE THEIR TOTALS. One call carrying the name is
    enough to find the customer; the row then shows their WHOLE history. A
    row-level search would count only the named calls and the figure would
    silently shrink."""
    installation = await installation_factory()
    await _call(call_factory, installation, contact_name="Anvar do'kon")
    await _call(call_factory, installation, contact_name=None)
    await _call(call_factory, installation, contact_name=None)

    body = (await manager.get(CLIENTS, params={**_window(), "search": "anvar"})).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["calls_total"] == 3


async def test_a_search_by_digits_ignores_the_format(
    manager, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await _call(call_factory, installation)
    body = (await manager.get(CLIENTS, params={**_window(), "search": "90 111"})).json()
    assert [row["phone_key"] for row in body["items"]] == [KEY]


async def test_a_search_by_code_finds_the_customer(
    manager, db, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await _call(call_factory, installation)
    db.add(ClientContactModel(phone_key=KEY, code="К00150", raw_name="K00150 Elyor"))
    await db.flush()
    body = (await manager.get(CLIENTS, params={**_window(), "search": "К00150"})).json()
    assert [row["phone_key"] for row in body["items"]] == [KEY]


async def test_a_percent_sign_does_not_switch_the_search_off(
    manager, call_factory, installation_factory
) -> None:
    installation = await installation_factory()
    await _call(call_factory, installation, contact_name="Anvar")
    body = (await manager.get(CLIENTS, params={**_window(), "search": "%"})).json()
    assert body["items"] == [], "unescaped, one % would match every customer"


# ── Paging ────────────────────────────────────────────────────


async def test_a_keyset_pass_returns_every_customer_exactly_once(
    manager, call_factory, installation_factory
) -> None:
    """The guarantee keyset exists for: no row skipped, none served twice."""
    installation = await installation_factory()
    for index in range(7):
        await _call(
            call_factory, installation, remote_number=f"+99890111{index:04d}"
        )

    seen: list[str] = []
    params = {**_window(), "limit": "3"}
    while True:
        body = (await manager.get(CLIENTS, params=params)).json()
        seen.extend(row["phone_key"] for row in body["items"])
        if not body["has_more"]:
            break
        params = {**_window(), "limit": "3", "cursor": body["next_cursor"]}

    assert len(seen) == 7
    assert len(set(seen)) == 7


async def test_customers_with_no_score_sort_last_in_both_directions(
    manager, call_factory, installation_factory, score_factory
) -> None:
    """⚠️ NULLS LAST both ways. PostgreSQL's default is NULLS FIRST for ASC, so
    "worst first" would open onto every unscored customer and the column would
    look empty."""
    installation = await installation_factory()
    scored = await _call(call_factory, installation, remote_number="+998901110001")
    await score_factory(call=scored, overall_score=70)
    await _call(call_factory, installation, remote_number="+998901110002")

    for order in ("desc", "asc"):
        body = (
            await manager.get(
                CLIENTS, params={**_window(), "sort": "score", "order": order}
            )
        ).json()
        assert body["items"][0]["phone_key"] == "901110001", order


async def test_a_tampered_cursor_is_400(manager) -> None:
    assert (
        await manager.get(CLIENTS, params={"cursor": "not-a-cursor!!"})
    ).status_code == 400


async def test_only_the_first_page_carries_a_total(
    manager, call_factory, installation_factory
) -> None:
    """A count over a grouped aggregate is affordable once per filter change
    and not once per page — the rule ``/calls`` already follows."""
    installation = await installation_factory()
    for index in range(3):
        await _call(call_factory, installation, remote_number=f"+99890111{index:04d}")

    first = (
        await manager.get(
            CLIENTS, params={**_window(), "limit": "2", "with_total": "true"}
        )
    ).json()
    assert first["total"] == 3
    second = (
        await manager.get(
            CLIENTS, params={**_window(), "limit": "2", "cursor": first["next_cursor"]}
        )
    ).json()
    assert second["total"] is None


# ── The card ──────────────────────────────────────────────────


async def test_the_card_shows_who_spoke_to_the_customer(
    manager, call_factory, installation_factory, agent_factory
) -> None:
    """A manager's first question: one customer, several employees (a handover,
    a holiday, a change of job)."""
    aziz = await installation_factory(agent=await agent_factory(full_name="Aziz"))
    nodira = await installation_factory(agent=await agent_factory(full_name="Nodira"))
    await _call(call_factory, aziz)
    await _call(call_factory, aziz)
    await _call(call_factory, nodira)

    body = (await manager.get(f"{CLIENTS}/{KEY}", params=_window())).json()
    assert body["client"]["calls_total"] == 3
    assert body["client"]["agent_count"] == 2
    assert [agent["full_name"] for agent in body["agents"]] == ["Aziz", "Nodira"]
    assert body["agents"][0]["calls"] == 2


async def test_an_empty_period_opens_the_card_with_zeros(
    manager, call_factory, installation_factory
) -> None:
    """⚠️ "No contact in the chosen period" is NOT "no such customer".
    Otherwise narrowing the dates tells the reader the customer does not
    exist."""
    installation = await installation_factory()
    await _call(call_factory, installation, started_at=NOON - timedelta(days=30))

    response = await manager.get(f"{CLIENTS}/{KEY}", params=_window())
    assert response.status_code == 200
    body = response.json()
    assert body["client"]["calls_total"] == 0
    assert body["client"]["first_call_at"] is None
    assert body["client"]["phone_key"] == KEY


async def test_a_card_link_without_a_scope_still_opens_an_internal_number(
    manager, call_factory, installation_factory
) -> None:
    """⚠️ The cut is a VIEW of the list, not a truth about the customer. A
    saved or hand-typed link carries no ``scope``, and answering 404 there
    teaches people the system is broken."""
    installation = await installation_factory()
    await _call(call_factory, installation, call_type=CallType.INTERNAL)

    body = (await manager.get(f"{CLIENTS}/{KEY}", params=_window())).json()
    assert body["client"]["calls_total"] == 1
    assert body["scope"] == "all", "the answer says which cut found them"


async def test_the_calls_list_widens_the_same_way(
    manager, call_factory, installation_factory
) -> None:
    """Otherwise the internal number's card opens above an empty table."""
    installation = await installation_factory()
    await _call(call_factory, installation, call_type=CallType.INTERNAL)
    body = (await manager.get(f"{CLIENTS}/{KEY}/calls", params=_window())).json()
    assert len(body["items"]) == 1


async def test_the_calls_list_is_newest_first(
    manager, call_factory, installation_factory
) -> None:
    """Ordered by when the CALL happened, not by when it was uploaded: a
    recovery sweep uploads yesterday's calls after today's, and a customer's
    history read in receipt order is not a history."""
    installation = await installation_factory()
    old = await _call(call_factory, installation, started_at=NOON - timedelta(hours=3))
    new = await _call(call_factory, installation, started_at=NOON)

    body = (await manager.get(f"{CLIENTS}/{KEY}/calls", params=_window())).json()
    assert [row["id"] for row in body["items"]] == [str(new.id), str(old.id)]


async def test_a_salesperson_sees_only_their_own_calls_on_the_card(
    sales, db, call_factory, installation_factory, agent_factory
) -> None:
    mine = await _own(db, installation_factory, sales.principal.agent_id)
    colleague = await installation_factory(agent=await agent_factory())
    await _call(call_factory, mine)
    await _call(call_factory, colleague)

    body = (await sales.get(f"{CLIENTS}/{KEY}/calls", params=_window())).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["agent_id"] == str(sales.principal.agent_id)
