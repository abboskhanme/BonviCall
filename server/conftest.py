"""Test infrastructure (T154, CONVENTIONS.md §13).

**Tests run against ``bonvicall_test``. Never the dev database.** BonviZvonki
runs its suite against the live dev database behind a ``"pytest-fixture"`` name
prefix and a sweeper, and that convention caused a real incident recorded in
its own ``conftest.py``: the sales tests wrote to ``client_contacts``, that
table was missing from the sweeper, and test rows appeared among real clients
on the Contacts page. Here the separation is structural, and
:func:`_assert_test_database` refuses to run if anybody points the suite
somewhere else.

The schema is built by ``alembic upgrade head``, not by ``create_all``: the
generated key columns, the exclusion constraint and the audit trigger only
exist in the migration, and running it on every suite run is the drift check
T102 wants anyway.

This file sits at ``server/`` rather than ``server/tests/`` so that the module
suites under ``src/modules/<name>/tests/`` see the same fixtures. Twenty
modules must not invent twenty definitions of "a call".
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core import clock
from src.core.config import get_settings
from src.core.deps import Principal, get_current_principal, get_session
from src.core.enums import (
    PG_ENUM_TYPES,
    AppVariant,
    AudioCodec,
    AudioContainer,
    AudioMissingReason,
    CallDirection,
    CallDisposition,
    CallSource,
    CaptureRoute,
    InstallationStatus,
    UserRole,
)
from src.core.permissions import Role, permissions_for
from src.core.security import hash_password
from src.core.storage import LocalFsAudioStorage, build_audio_key, sha256_of
from src.main import create_app
from src.modules.agents.models import AgentModel
from src.modules.audio.models import CallAudioModel
from src.modules.auth.models import ServiceTokenModel
from src.modules.calls.models import CallModel
from src.modules.devices.models import DeviceModel
from src.modules.enrolment.models import EnrolmentCodeModel
from src.modules.installations.models import InstallationModel
from src.modules.installations.service import InstallationService
from src.modules.numbers.models import NumberAssignmentModel, RegisteredNumberModel
from src.modules.settings.models import AppSettingModel
from src.modules.users.models import UserModel

SERVER_DIR = Path(__file__).resolve().parent

#: Not a real argon2 hash, so an account built with it cannot log in. That is
#: deliberate: most fixtures only need a row, and hashing costs ~50 ms each.
#: Pass ``password=`` to ``user_factory`` when the test actually logs in.
PLACEHOLDER_PASSWORD_HASH = "x" * 64

#: The password every test that logs in uses. Ten characters, per SPEC §4.7.
TEST_PASSWORD = "correct-horse-battery"


def _assert_test_database(url: str) -> None:
    """Refuse to touch anything that is not obviously the test database."""
    settings = get_settings()
    if url == settings.database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL equals DATABASE_URL. The suite truncates tables; "
            "pointing it at the dev database is the BonviZvonki incident (§13)."
        )
    # Split the query first: a unix-socket URL carries the socket directory
    # in ?host=/var/run/... and that path contains slashes of its own.
    database_name = url.split("?", 1)[0].rsplit("/", 1)[-1]
    if not database_name.endswith("_test"):
        raise RuntimeError(
            f"refusing to run the suite against {database_name!r}: the test "
            "database name must end in '_test'."
        )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = get_settings().test_database_url
    _assert_test_database(url)
    return url


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    """``alembic upgrade head`` on the test database, once per session.

    Every suite run therefore exercises the real migration — extensions,
    generated columns, the exclusion constraint and the audit trigger included.
    """
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    config.cmd_opts = type("Opts", (), {"x": [f"db_url={test_database_url}"]})()
    command.upgrade(config, "head")
    if not _settings_seeded(test_database_url) or not _enums_match_code(
        test_database_url
    ):
        # Two ways an already-migrated database can be silently wrong:
        #
        # 1. Its seed rows were wiped. The seed lives in the migration, so it
        #    never comes back — one committed TRUNCATE does it, and every later
        #    assertion about a threshold then fails for a reason nobody sees.
        # 2. **Revision 001 was edited.** It is the pre-release baseline and may
        #    still be (docs/ASSUMPTIONS.md), but ``upgrade head`` on a database
        #    already stamped 001 does nothing, so the schema keeps the old
        #    shape. That is not hypothetical: two enum values were added and the
        #    suite failed with "invalid input value for enum audit_action".
        #
        # Rebuilding is cheap and this is the throwaway database. The check goes
        # away when 001 freezes at the first deploy (W03).
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    return test_database_url


def _enums_match_code(url: str) -> bool:
    """Whether every PostgreSQL enum still has the labels the code declares."""

    async def _check() -> bool:
        engine = create_async_engine(url, poolclass=sa.pool.NullPool)
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(
                    sa.text(
                        "SELECT t.typname, e.enumlabel "
                        "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                        "JOIN pg_namespace n ON n.oid = t.typnamespace "
                        "WHERE n.nspname = 'public'"
                    )
                )
            stored: dict[str, set[str]] = {}
            for type_name, label in rows:
                stored.setdefault(type_name, set()).add(label)
        finally:
            await engine.dispose()
        return all(
            stored.get(name) == {member.value for member in enum_class}
            for name, enum_class in PG_ENUM_TYPES.items()
        )

    return asyncio.run(_check())


def _settings_seeded(url: str) -> bool:
    """True when ``app_settings`` still holds the migration's seed."""

    async def _count() -> int:
        engine = create_async_engine(url, poolclass=sa.pool.NullPool)
        try:
            async with engine.connect() as connection:
                return await connection.scalar(
                    sa.text("SELECT count(*) FROM app_settings")
                )
        finally:
            await engine.dispose()

    return asyncio.run(_count()) > 0


@pytest.fixture(scope="session")
def engine(migrated_database: str):
    engine = create_async_engine(migrated_database, poolclass=sa.pool.NullPool)
    yield engine


@pytest_asyncio.fixture
async def db(engine) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back when the test ends.

    Nothing a test writes survives it, so tests are order-independent by
    construction rather than by a sweeper somebody has to remember to update.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        maker = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        session = maker()
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def truncate_all(db: AsyncSession) -> Callable[[], Any]:
    """Empty every table and restore the migration's settings seed.

    Runs on the **test session's own connection**, not a second one: TRUNCATE
    takes an ACCESS EXCLUSIVE lock, and issuing it from another connection
    while ``db`` holds an open transaction on the same tables deadlocks until
    the suite times out.

    ``app_settings`` cannot simply be excluded — it has a foreign key to
    ``users``, so truncating ``users`` reaches it through CASCADE whatever the
    list says. It is therefore snapshotted and put back, because a settings
    table that is empty makes every later assertion about a threshold a lie.

    Tables are truncated, never dropped: dropping them would mean re-running
    the migration per test, and the point of the session-scoped upgrade is that
    it runs once and is proven once.
    """

    async def _truncate() -> None:
        seeded = (
            await db.execute(sa.select(AppSettingModel).order_by(AppSettingModel.key))
        ).scalars().all()
        snapshot = [
            {
                "key": row.key,
                "value": row.value,
                "value_type": row.value_type,
                "description_uz": row.description_uz,
            }
            for row in seeded
        ]
        rows = await db.execute(
            sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = [name for (name,) in rows if name != "alembic_version"]
        db.expunge_all()
        await db.execute(
            sa.text(
                "TRUNCATE TABLE "
                + ", ".join(f'"{name}"' for name in names)
                + " RESTART IDENTITY CASCADE"
            )
        )
        if snapshot:
            await db.execute(sa.insert(AppSettingModel), snapshot)

    return _truncate


@pytest.fixture(autouse=True)
def audio_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway storage root, pointed at by the settings the services read.

    **Autouse**, and that is the point: §13 asks for isolation by construction
    rather than by discipline, so no test can write into the real audio volume
    even by forgetting to ask. Patching the settings object rather than the
    fixture alone is what makes ``AudioService`` and ``audio_factory`` agree
    about where a file is — they did not, and every playback test 404'd.
    """
    root = tmp_path / "audio"
    LocalFsAudioStorage(root).ensure_ready()
    monkeypatch.setattr(get_settings(), "audio_storage_path", root)
    return root


def build_app(db: AsyncSession) -> FastAPI:
    """An application instance wired to the test session and nothing else."""
    application = create_app()

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db

    application.dependency_overrides[get_session] = _session_override
    return application


@pytest.fixture
def app(db: AsyncSession) -> FastAPI:
    """An unauthenticated application instance, for the ``client`` fixture."""
    return build_app(db)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An unauthenticated HTTP client. Use it for the 401 half of every RBAC test."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client


def _principal_for(user: UserModel) -> Principal:
    return Principal(
        kind="user",
        id=user.id,
        role=str(user.role),
        permissions=permissions_for(str(user.role)),
        agent_id=user.agent_id,
        display_name=user.full_name,
    )


@pytest_asyncio.fixture
async def user_factory(db: AsyncSession, agent_factory) -> Callable[..., Any]:
    """Create a panel account. A ``sales`` account gets an agent, as the CHECK requires."""
    counter = {"n": 0}

    async def _create(role: UserRole, **overrides: Any) -> UserModel:
        counter["n"] += 1
        agent = overrides.pop("agent", None)
        if role is UserRole.SALES and agent is None:
            agent = await agent_factory()
        password = overrides.pop("password", None)
        user = UserModel(
            email=overrides.pop("email", f"{role.value}{counter['n']}@bonvi.uz"),
            password_hash=(
                hash_password(password) if password else PLACEHOLDER_PASSWORD_HASH
            ),
            full_name=overrides.pop("full_name", f"Test {role.value}"),
            role=role,
            agent_id=agent.id if agent is not None else None,
            **overrides,
        )
        db.add(user)
        await db.flush()
        return user

    return _create


async def _authenticated_client(db: AsyncSession, principal: Principal) -> AsyncClient:
    """A client on its **own** application instance.

    ``dependency_overrides`` is per application, so sharing one instance means
    the last role fixture requested wins for every client. That is not a
    theoretical problem: it made a four-role test assert 405 four times as the
    same role, and it made a device client authenticate as an admin. Both
    reported safety they were not testing, which is the worst thing a suite can
    do.
    """
    application = build_app(db)
    application.dependency_overrides[get_current_principal] = lambda: principal
    return AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    )


@pytest_asyncio.fixture
async def admin(db: AsyncSession, user_factory) -> AsyncIterator[AsyncClient]:
    """A client authenticated as ``admin``."""
    user = await user_factory(UserRole.ADMIN)
    async with await _authenticated_client(db, _principal_for(user)) as http_client:
        http_client.principal = _principal_for(user)  # type: ignore[attr-defined]
        yield http_client


@pytest_asyncio.fixture
async def manager(db: AsyncSession, user_factory) -> AsyncIterator[AsyncClient]:
    """A client authenticated as ``manager``."""
    user = await user_factory(UserRole.MANAGER)
    async with await _authenticated_client(db, _principal_for(user)) as http_client:
        http_client.principal = _principal_for(user)  # type: ignore[attr-defined]
        yield http_client


@pytest_asyncio.fixture
async def sales(db: AsyncSession, user_factory) -> AsyncIterator[AsyncClient]:
    """A client authenticated as ``sales``, linked to an agent (own-scope needs it)."""
    user = await user_factory(UserRole.SALES)
    async with await _authenticated_client(db, _principal_for(user)) as http_client:
        http_client.principal = _principal_for(user)  # type: ignore[attr-defined]
        yield http_client


@pytest_asyncio.fixture
async def viewer(db: AsyncSession, user_factory) -> AsyncIterator[AsyncClient]:
    """A client authenticated as ``viewer`` — the sales-room TV."""
    user = await user_factory(UserRole.VIEWER)
    async with await _authenticated_client(db, _principal_for(user)) as http_client:
        http_client.principal = _principal_for(user)  # type: ignore[attr-defined]
        yield http_client


@pytest_asyncio.fixture
async def service_token(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """A client authenticated as the machine principal (UC-29), plus its row."""
    token = ServiceTokenModel(
        name=f"export-{uuid.uuid4().hex[:8]}",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        scopes=["export:read", "export:audio"],
    )
    db.add(token)
    await db.flush()
    principal = Principal(
        kind="service",
        id=token.id,
        role=str(Role.SERVICE),
        permissions=permissions_for(str(Role.SERVICE)),
        display_name=token.name,
    )
    async with await _authenticated_client(db, principal) as http_client:
        http_client.principal = principal  # type: ignore[attr-defined]
        http_client.token_row = token  # type: ignore[attr-defined]
        yield http_client


@pytest.fixture
def agent_factory(db: AsyncSession) -> Callable[..., Any]:
    """Create an agent. **Every test creates data through a factory** (§13)."""
    counter = {"n": 0}

    async def _create(**overrides: Any) -> AgentModel:
        counter["n"] += 1
        agent = AgentModel(
            full_name=overrides.pop("full_name", f"Agent {counter['n']}"),
            **overrides,
        )
        db.add(agent)
        await db.flush()
        return agent

    return _create


@pytest.fixture
def registered_number_factory(db: AsyncSession, agent_factory) -> Callable[..., Any]:
    """Create a registered number, optionally assigned to an agent from a moment.

    Passing ``agent`` creates the open-ended assignment as well, because a
    number nobody holds cannot attribute a call and every caller of this
    factory would otherwise write those four lines again.
    """
    counter = {"n": 0}

    async def _create(**overrides: Any) -> RegisteredNumberModel:
        counter["n"] += 1
        agent = overrides.pop("agent", None)
        created_by = overrides.pop("created_by", None)
        valid_from = overrides.pop(
            "valid_from", datetime.now(UTC) - timedelta(days=365)
        )
        number = RegisteredNumberModel(
            e164=overrides.pop("e164", f"+9989011122{counter['n']:02d}"),
            **overrides,
        )
        db.add(number)
        await db.flush()
        if agent is not None:
            if created_by is None:
                created_by = UserModel(
                    email=f"assigner{counter['n']}@bonvi.uz",
                    password_hash=PLACEHOLDER_PASSWORD_HASH,
                    full_name="Assigner",
                    role=UserRole.ADMIN,
                )
                db.add(created_by)
                await db.flush()
            db.add(
                NumberAssignmentModel(
                    number_id=number.id,
                    agent_id=agent.id,
                    valid_from=valid_from,
                    created_by=created_by.id,
                )
            )
            await db.flush()
        await db.refresh(number)
        return number

    return _create


@pytest.fixture
def device_factory(db: AsyncSession) -> Callable[..., Any]:
    """Create a handset row."""
    counter = {"n": 0}

    async def _create(**overrides: Any) -> DeviceModel:
        counter["n"] += 1
        device = DeviceModel(
            manufacturer=overrides.pop("manufacturer", "Xiaomi"),
            model=overrides.pop("model", "Redmi Note 12"),
            android_release=overrides.pop("android_release", "13"),
            api_level=overrides.pop("api_level", 33),
            build_fingerprint_hash=overrides.pop(
                "build_fingerprint_hash", f"{counter['n']:064d}"
            ),
            **overrides,
        )
        db.add(device)
        await db.flush()
        return device

    return _create


@pytest.fixture
def installation_factory(
    db: AsyncSession, agent_factory, registered_number_factory, device_factory
) -> Callable[..., Any]:
    """Create an installation, with its agent, number and handset if not supplied."""
    counter = {"n": 0}

    async def _create(**overrides: Any) -> InstallationModel:
        counter["n"] += 1
        agent = overrides.pop("agent", None) or await agent_factory()
        number = overrides.pop("number", None) or await registered_number_factory(
            agent=agent
        )
        device = overrides.pop("device", None) or await device_factory()
        installation = InstallationModel(
            number_id=number.id,
            agent_id=agent.id,
            device_id=device.id,
            status=overrides.pop("status", InstallationStatus.ACTIVE),
            credential_hash=overrides.pop("credential_hash", f"{counter['n']:064d}"),
            device_fingerprint_hash=overrides.pop(
                "device_fingerprint_hash", f"{counter['n']:064d}"
            ),
            bound_at=overrides.pop("bound_at", datetime.now(UTC)),
            **overrides,
        )
        db.add(installation)
        await db.flush()
        return installation

    return _create


@pytest.fixture
def call_factory(db: AsyncSession, installation_factory) -> Callable[..., Any]:
    """Create a call that satisfies the four CHECK constraints by construction.

    Answered calls get an ``answered_at`` and a non-zero duration; unanswered
    calls get neither. A test that wants to prove a constraint rejects
    something builds that row itself — this factory exists so that the other
    nineteen tests do not have to think about it.
    """
    counter = {"n": 0}

    async def _create(**overrides: Any) -> CallModel:
        counter["n"] += 1
        installation = overrides.pop("installation", None) or await installation_factory()
        started_at = overrides.pop(
            "started_at", datetime.now(UTC) - timedelta(minutes=counter["n"])
        )
        disposition = overrides.pop("disposition", CallDisposition.ANSWERED)
        answered = disposition is CallDisposition.ANSWERED
        duration_sec = overrides.pop("duration_sec", 120 if answered else 0)
        has_audio = overrides.pop("has_audio", False)
        reason = overrides.pop(
            "audio_missing_reason",
            None if has_audio else AudioMissingReason.PENDING_UPLOAD,
        )
        call = CallModel(
            client_call_id=overrides.pop("client_call_id", uuid.uuid4()),
            installation_id=installation.id,
            number_id=installation.number_id,
            agent_id=installation.agent_id,
            direction=overrides.pop("direction", CallDirection.OUTGOING),
            disposition=disposition,
            remote_number=overrides.pop("remote_number", "+998935554433"),
            started_at=started_at,
            answered_at=overrides.pop(
                "answered_at", started_at + timedelta(seconds=9) if answered else None
            ),
            ended_at=overrides.pop("ended_at", started_at + timedelta(seconds=duration_sec)),
            duration_sec=duration_sec,
            device_epoch_ms=overrides.pop(
                "device_epoch_ms", int(started_at.timestamp() * 1000)
            ),
            device_timezone=overrides.pop("device_timezone", "Asia/Tashkent"),
            # Explicit, and distinct per row: PostgreSQL's now() is the
            # *transaction* timestamp, so rows created in one test would all
            # share it and any assertion about ordering would pass by luck.
            received_at=overrides.pop(
                "received_at",
                datetime.now(UTC) + timedelta(microseconds=counter["n"]),
            ),
            source=overrides.pop("source", CallSource.LIVE_CAPTURE),
            has_audio=has_audio,
            audio_missing_reason=reason,
            app_version=overrides.pop("app_version", "1.0.0"),
            app_variant=overrides.pop("app_variant", AppVariant.MODERN34),
            **overrides,
        )
        db.add(call)
        await db.flush()
        await db.refresh(call)
        return call

    return _create


@pytest.fixture
def audio_factory(
    db: AsyncSession, call_factory, audio_root: Path
) -> Callable[..., Any]:
    """Create a stored recording **and the bytes behind it**.

    The file is real so that Range requests, checksums and the retention job
    can be tested against something rather than against a row that claims a
    file exists.
    """

    async def _create(**overrides: Any) -> CallAudioModel:
        payload: bytes = overrides.pop("payload", b"OggS" + b"\x00" * 4096)
        call = overrides.pop("call", None) or await call_factory(
            has_audio=True, audio_missing_reason=None
        )
        recorded_at = overrides.pop("recorded_at", call.started_at)
        key = overrides.pop("storage_key", build_audio_key(call.id, recorded_at, "ogg"))
        target = audio_root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        audio = CallAudioModel(
            call_id=call.id,
            storage_key=key,
            bytes=len(payload),
            sha256=overrides.pop("sha256", sha256_of(target)),
            codec=overrides.pop("codec", AudioCodec.OPUS),
            container=overrides.pop("container", AudioContainer.OGG),
            capture_route=overrides.pop("capture_route", CaptureRoute.OEM_FILE_HARVEST),
            recorded_at=recorded_at,
            **overrides,
        )
        db.add(audio)
        await db.flush()
        return audio

    return _create


@pytest.fixture
def enrolment_code_factory(db: AsyncSession, user_factory, registered_number_factory):
    """Issue a code the way the panel does, so redemption tests are realistic."""

    async def _create(**overrides: Any) -> EnrolmentCodeModel:
        issuer = overrides.pop("issued_by", None) or await user_factory(UserRole.ADMIN)
        agent = overrides.pop("agent", None) or await agent_factory_of(db)
        number = overrides.pop("number", None) or await registered_number_factory(
            agent=agent, created_by=issuer
        )
        code = EnrolmentCodeModel(
            code=overrides.pop("code", f"K7M4PQ{uuid.uuid4().hex[:2].upper()}"),
            number_id=number.id,
            agent_id=agent.id,
            issued_by=issuer.id,
            expires_at=overrides.pop(
                "expires_at", datetime.now(UTC) + timedelta(hours=24)
            ),
            **overrides,
        )
        db.add(code)
        await db.flush()
        return code

    return _create


async def agent_factory_of(session: AsyncSession) -> AgentModel:
    """An agent, for fixtures that cannot take the ``agent_factory`` fixture."""
    agent = AgentModel(full_name=f"Agent {uuid.uuid4().hex[:6]}")
    session.add(agent)
    await session.flush()
    return agent


@pytest_asyncio.fixture
async def device_client_factory(db: AsyncSession):
    """A client holding a **real** installation token, with the required headers.

    Real rather than a dependency override, because the device half of N24 —
    the token's claims matching ``X-Installation-Id`` and
    ``X-Device-Fingerprint`` — only exists in the resolver, and overriding the
    principal would skip exactly the check the tests are for.
    """
    clients: list[AsyncClient] = []
    # Its own instance, so a panel-role fixture in the same test cannot
    # override this client's principal out from under it.
    device_app = build_app(db)

    async def _create(installation: InstallationModel, **header_overrides: str):
        pair = await InstallationService(db).issue_device_pair(installation)
        await db.flush()
        headers = {
            "Authorization": f"Bearer {pair.access_token}",
            "X-App-Version": "1.0.0",
            "X-App-Version-Code": "100",
            "X-Installation-Id": str(installation.id),
            "X-Device-Fingerprint": installation.device_fingerprint_hash,
        }
        headers.update(header_overrides)
        http_client = AsyncClient(
            transport=ASGITransport(app=device_app),
            base_url="http://testserver",
            headers=headers,
        )
        http_client.refresh_token = pair.refresh_token  # type: ignore[attr-defined]
        clients.append(http_client)
        return http_client

    yield _create
    for http_client in clients:
        await http_client.aclose()


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[datetime], None]]:
    """Pin ``core.clock.now()``.

    Code under test must call ``clock.now()`` through the module, not import
    the function — that is what makes the clock patchable in one place, and it
    is the same reason ``core/clock.py`` is the only module allowed to call
    ``datetime.now()`` at all (§6).
    """
    state = {"now": datetime(2026, 9, 4, 9, 0, tzinfo=UTC)}

    def _set(moment: datetime) -> None:
        state["now"] = moment

    monkeypatch.setattr(clock, "now", lambda: state["now"])
    yield _set
