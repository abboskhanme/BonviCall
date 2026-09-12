"""The shared fixtures themselves (T154, CONVENTIONS.md §13).

Twenty modules will build their test data through these. A factory that is
subtly wrong is twenty subtly wrong test suites, so the factories are tested
here once, where the failure is legible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.core import clock
from src.core.enums import CallDisposition, InstallationStatus
from src.core.permissions import Perm

pytestmark = pytest.mark.asyncio


async def test_the_suite_refuses_a_database_that_is_not_the_test_one() -> None:
    """The BonviZvonki incident, made structurally impossible (§13)."""
    from conftest import _assert_test_database

    with pytest.raises(RuntimeError, match="must end in '_test'"):
        _assert_test_database("postgresql+asyncpg://u:p@host:5432/bonvicall")


async def test_db_rolls_back_between_tests(db, agent_factory) -> None:
    """Two tests, one name: the second would fail if the first had persisted."""
    await agent_factory(full_name="Rollback Probe")
    count = await db.scalar(
        sa.text("SELECT count(*) FROM agents WHERE full_name = 'Rollback Probe'")
    )
    assert count == 1


async def test_db_rolls_back_between_tests_again(db, agent_factory) -> None:
    count = await db.scalar(
        sa.text("SELECT count(*) FROM agents WHERE full_name = 'Rollback Probe'")
    )
    assert count == 0


async def test_role_clients_carry_the_right_permissions(
    admin, manager, sales, service_token
) -> None:
    assert admin.principal.has(Perm.AUDIT_READ)
    assert not manager.principal.has(Perm.AUDIT_READ)
    assert sales.principal.has(Perm.CALLS_READ_OWN)
    assert not sales.principal.has(Perm.CALLS_READ)
    assert service_token.principal.has(Perm.EXPORT_READ)


async def test_a_sales_principal_is_linked_to_an_agent(sales) -> None:
    """Own-scope narrowing filters on this; without it the fixture proves nothing."""
    assert sales.principal.agent_id is not None


async def test_registered_number_factory_assigns_when_asked(
    db, agent_factory, registered_number_factory
) -> None:
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent)
    assert number.phone_key == number.e164[-9:]
    holder = await db.scalar(
        sa.select(sa.func.count())
        .select_from(sa.table("number_assignments"))
        .where(sa.column("number_id") == number.id)
    )
    assert holder == 1


async def test_installation_factory_creates_the_whole_chain(
    installation_factory,
) -> None:
    installation = await installation_factory()
    assert installation.status is InstallationStatus.ACTIVE
    assert installation.number_id and installation.agent_id and installation.device_id


async def test_call_factory_satisfies_the_check_constraints(call_factory) -> None:
    answered = await call_factory()
    assert answered.disposition is CallDisposition.ANSWERED
    assert answered.answered_at is not None and answered.duration_sec > 0

    unanswered = await call_factory(disposition=CallDisposition.NO_ANSWER)
    assert unanswered.answered_at is None and unanswered.duration_sec == 0


async def test_audio_factory_writes_real_bytes(audio_factory, audio_root) -> None:
    """Range requests and checksums need a file, not a row that claims one."""
    audio = await audio_factory(payload=b"OggS" + b"\x01" * 1024)
    path = audio_root / audio.storage_key
    assert path.is_file()
    assert path.stat().st_size == audio.bytes == 1028


async def test_frozen_clock_pins_now(frozen_clock) -> None:
    moment = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    frozen_clock(moment)
    assert clock.now() == moment
    frozen_clock(moment + timedelta(hours=5))
    assert clock.now() == moment + timedelta(hours=5)


async def test_truncate_all_leaves_the_seeded_settings(db, truncate_all) -> None:
    """Truncation must not delete the migration's seed, or every later test lies."""
    await truncate_all()
    remaining = await db.scalar(sa.text("SELECT count(*) FROM app_settings"))
    assert remaining == 29
