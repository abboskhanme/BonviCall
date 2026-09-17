"""The daily message: the four guards, the replay guard — and the network.

Ported in intent from BonviZvonki ``tests/test_digest.py``.

═══ THE LOAD-BEARING TEST IN THIS FILE ═════════════════════════════════════
``test_nothing_in_this_module_can_reach_the_network``. In BonviZvonki this
module posts to ``api.telegram.org``, and a message delivered to the wrong
group cannot be taken back. Here the transport is a seam whose only
implementation writes a log line, and there is no HTTP client and no bot token
anywhere in the module. That is asserted by reading the source, because an
assertion about behaviour could only ever prove that one path did not call out.

**Do not weaken this test to let a transport through.** Adding one is a
deliberate piece of work: an implementation of ``telegram.DigestSender``
registered through ``set_sender``, with its token in ``core/config.py`` beside
the other credentials — never in ``app_settings``, which every manager can read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.core.settings_keys import SettingKey
from src.modules.sales.digest import SalesDigestService
from src.modules.sales.models import SaleDigestModel
from src.modules.sales.telegram import LoggingDigestSender, SendResult
from src.modules.sales.tests.conftest import SALE_DAY

pytestmark = pytest.mark.asyncio

NOON = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
MODULE = Path(__file__).resolve().parents[1]

CHAT = "-1001234567890"


@pytest.fixture
def digest_world(partner_factory, sale_factory, call_factory, installation_factory, agent_factory):
    """One clean sale, one suspicious sale, on the same day."""

    async def _build():
        installation = await installation_factory(
            agent=await agent_factory(full_name="Aziz")
        )
        clean = await partner_factory(code="К80011", name="Toza")
        dirty = await partner_factory(code="К80022", name="Shubhali")
        await sale_factory(partner=clean, external_id="OP-CLEAN")
        await sale_factory(
            partner=dirty, external_id="OP-DIRTY", amount_usd=Decimal("5610")
        )
        await call_factory(
            installation=installation, remote_number=clean.phone, started_at=NOON
        )

    return _build


# ══════════════════════════════════════════════════════════════
#  The seam
# ══════════════════════════════════════════════════════════════
#
# The three source-level guarantees — no transport, no token, and the only
# sender being the logging one — live in ``test_sales_rules.py``: they need
# no session, and this file is marked ``asyncio`` throughout.


async def test_the_logging_sender_says_why() -> None:
    result = await LoggingDigestSender().send(chat_id=CHAT, text="hello")
    assert result == SendResult(ok=False, error="no_transport_configured")


async def test_the_test_endpoint_hands_the_text_to_the_seam_and_no_further(
    admin, db, digest_world, set_sales_setting
) -> None:
    """The button's whole purpose: see what WOULD go out. It comes back with the
    text and ``sent=false``, which is the honest report."""
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)

    body = (await admin.post("/api/v1/sales/digest/test")).json()
    assert body["sent"] is False
    assert body["reason"] == "send_failed"
    assert body["error"] == "no_transport_configured"
    assert "Savdo nazorati" in body["text"]
    assert body["chars"] == len(body["text"])
    assert body["day"] == SALE_DAY.isoformat()


# ══════════════════════════════════════════════════════════════
#  The four guards
# ══════════════════════════════════════════════════════════════


async def test_the_scheduled_run_is_off_by_default(db, digest_world) -> None:
    """⚠️ Guard 1, and the default. With the switch off the text is not even
    assembled — deploying this must be a no-op on a running system."""
    await digest_world()
    outcome = await SalesDigestService(db).run(manual=False)

    assert (outcome.sent, outcome.reason) == (False, "disabled")
    assert outcome.text == "", "not even assembled"


async def test_the_test_button_ignores_the_switch(
    db, digest_world, set_sales_setting
) -> None:
    """That is the entire point of the button: see the text BEFORE turning the
    switch on."""
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)

    outcome = await SalesDigestService(db).run(manual=True)
    assert outcome.text != ""


async def test_an_empty_chat_stops_it_but_still_returns_the_text(
    db, digest_world
) -> None:
    """⚠️ Guard 2. Not silently — a warning is logged, and the text comes back
    so the panel can say "now name a chat" instead of answering 422."""
    await digest_world()
    outcome = await SalesDigestService(db).run(manual=True)

    assert (outcome.sent, outcome.reason) == (False, "no_chat")
    assert "Savdo nazorati" in outcome.text


async def test_a_database_with_no_sales_produces_no_message(db) -> None:
    outcome = await SalesDigestService(db).run(manual=True)
    assert (outcome.sent, outcome.reason) == (False, "no_sales")


# ══════════════════════════════════════════════════════════════
#  The replay guard
# ══════════════════════════════════════════════════════════════


async def test_a_second_scheduled_run_with_no_new_import_sends_nothing(
    db, digest_world, set_sales_setting
) -> None:
    """⚠️ A scheduler is not a guarantee: a container recreated at the wrong
    moment runs the job twice in one day. The same message arriving twice is
    noise, and noise is what stops it being read — so the guard lives HERE."""
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_ENABLED, True)
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)
    service = SalesDigestService(db)

    first = await service.run(manual=False)
    assert first.reason == "send_failed", "the seam refused, as it must"

    # A failed attempt does NOT move the watermark — otherwise a transport that
    # fell over once would lose the message for ever.
    second = await service.run(manual=False)
    assert second.reason == "send_failed"

    # Pretend the transport had accepted it.
    row = await db.scalar(select(SaleDigestModel))
    row.ok = True
    await db.flush()

    third = await service.run(manual=False)
    assert third.reason == "no_new_import"
    assert third.day == SALE_DAY


async def test_a_test_message_does_not_move_the_watermark(
    db, digest_world, set_sales_setting
) -> None:
    """⚠️ One press of "try it" would otherwise switch off that night's real
    message — the guard looks at ``kind = 'daily'`` only."""
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_ENABLED, True)
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)
    service = SalesDigestService(db)

    await service.run(manual=True)
    row = await db.scalar(select(SaleDigestModel))
    assert row.kind == "test"
    row.ok = True
    await db.flush()

    assert await service.last_sent_watermark() is None
    assert (await service.run(manual=False)).reason != "no_new_import"


async def test_a_new_import_reopens_the_gate(
    db, digest_world, sale_factory, partner_factory, set_sales_setting
) -> None:
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_ENABLED, True)
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)
    service = SalesDigestService(db)

    await service.run(manual=False)
    row = await db.scalar(select(SaleDigestModel))
    row.ok = True
    await db.flush()
    assert (await service.run(manual=False)).reason == "no_new_import"

    partner = await partner_factory(code="К80099")
    await sale_factory(
        partner=partner,
        external_id="OP-FRESH",
        imported_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert (await service.run(manual=False)).reason == "send_failed"


async def test_every_attempt_is_written_to_the_log_table(
    db, digest_world, set_sales_setting
) -> None:
    """This is the only action in the product that would leave the machine.
    "When, to which chat, for which day, did it go" has to be answerable."""
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)

    await SalesDigestService(db).run(manual=True)
    row = await db.scalar(select(SaleDigestModel))
    assert row.kind == "test"
    assert row.covered_on == SALE_DAY
    assert row.chat_id == CHAT
    assert row.ok is False
    assert row.error == "no_transport_configured"
    assert row.watermark is not None


async def test_the_message_text_is_not_stored(db, digest_world, set_sales_setting) -> None:
    """It is reassembled from live data every time, like the verdict itself; a
    second copy would grow this table by tens of megabytes a year."""
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)
    await SalesDigestService(db).run(manual=True)

    assert not any(
        "text" in column.name for column in SaleDigestModel.__table__.columns
    )


# ══════════════════════════════════════════════════════════════
#  The figures
# ══════════════════════════════════════════════════════════════


async def test_the_figures_come_from_the_compliance_service(db, digest_world) -> None:
    """⚠️ "41 suspicious" in the message must be the same number as on the
    screen, or the manager does not know which to believe. So there is no new
    SQL in the digest."""
    await digest_world()
    data = await SalesDigestService(db).collect()

    assert data is not None
    assert (data.total, data.ok, data.suspicious, data.not_checkable) == (2, 1, 1, 0)
    assert data.window_days == 3
    assert [line.name for line in data.agents] == [None], "unlinked branch, own row"


async def test_the_day_is_the_last_imported_one_not_yesterday(
    db, partner_factory, sale_factory
) -> None:
    """⚠️ The SAP export is uploaded by hand and is usually a day or two behind.
    Insisting on yesterday produces a message about an EMPTY day again and
    again, and the manager stops reading it."""
    partner = await partner_factory()
    await sale_factory(partner=partner, occurred_on=SALE_DAY - timedelta(days=4))
    await sale_factory(
        partner=partner, external_id="OP-LATER", occurred_on=SALE_DAY
    )

    data = await SalesDigestService(db).collect()
    assert data is not None
    assert data.day == SALE_DAY


async def test_walk_in_sales_are_counted_separately(
    db, digest_world, partner_factory, sale_factory
) -> None:
    """⚠️ They are not in the main figures — the question has no meaning under a
    shared code — but the number does not VANISH: the manager knows the day's
    SAP total and a smaller one with no explanation reads as "the system is
    losing sales"."""
    await digest_world()
    walk_in = await partner_factory(code="К00001")
    await sale_factory(
        partner=walk_in, external_id="OP-WALKIN", amount_usd=Decimal("9000")
    )

    data = await SalesDigestService(db).collect()
    assert data is not None
    assert data.total == 2, "the walk-in sale is not in the headline figures"
    assert data.walk_in_total == 1
    assert data.walk_in_over_limit == 1
    assert data.walk_in_over_amount == 9000.0
    assert data.walk_in_limit == 2000


async def test_the_amount_threshold_never_hides_a_sale_of_unknown_value(
    db, partner_factory, sale_factory
) -> None:
    """⚠️ "I do not know" is not "small". Quietly dropping something we could
    not measure because of a money threshold is against the point."""
    partner = await partner_factory()
    await sale_factory(partner=partner, external_id="OP-SMALL", amount_usd=Decimal("5"))
    await sale_factory(partner=partner, external_id="OP-UNKNOWN", amount_usd=None)

    data = await SalesDigestService(db).collect(min_amount=1000)
    assert data is not None
    assert data.total == 1
    assert data.skipped_by_amount == 1
    assert [row.external_id for row in data.top] == ["OP-UNKNOWN"]


async def test_the_biggest_suspicious_sale_leads_the_message(
    db, partner_factory, sale_factory
) -> None:
    """The more money, the more a check is worth."""
    partner = await partner_factory()
    await sale_factory(partner=partner, external_id="OP-SMALL", amount_usd=Decimal("10"))
    await sale_factory(partner=partner, external_id="OP-BIG", amount_usd=Decimal("9000"))

    data = await SalesDigestService(db).collect()
    assert data is not None
    assert [row.external_id for row in data.top] == ["OP-BIG", "OP-SMALL"]


async def test_the_figures_ignore_whether_a_sale_has_been_reviewed(
    db, digest_world, sale_review_factory, db_sale_id
) -> None:
    """⚠️ With the default ``new`` filter, a manager who reviewed a few sales in
    the evening would get a message whose figures were LOWER than the panel's,
    and nobody could explain the difference."""
    await digest_world()
    await sale_review_factory(await db_sale_id("OP-DIRTY"), status="justified")

    data = await SalesDigestService(db).collect()
    assert data is not None
    assert data.total == 2, "a decided sale is still one of the day's sales"
    assert data.suspicious == 1


@pytest.fixture
def db_sale_id(db):
    async def _find(external_id: str):
        from src.modules.sales.models import SaleModel

        return await db.scalar(
            select(SaleModel.id).where(SaleModel.external_id == external_id)
        )

    return _find


async def test_a_digest_run_leaves_exactly_one_log_row(
    db, digest_world, set_sales_setting
) -> None:
    await digest_world()
    await set_sales_setting(SettingKey.SALES_DIGEST_CHAT_ID, CHAT)
    await SalesDigestService(db).run(manual=True)

    assert await db.scalar(select(func.count()).select_from(SaleDigestModel)) == 1
