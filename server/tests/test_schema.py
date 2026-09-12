"""What the database itself refuses (T147, SPEC §12 "Schema and data").

Every assertion here is about a rule that lives in PostgreSQL rather than in
Python, because each of them is a rule an application-level check would lose:
two admins clicking at once, a second phone claiming a number, a call the
ingest path forgot to give a reason to, somebody editing the audit log.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.core.enums import (
    ActorType,
    AppVariant,
    AuditAction,
    CallDirection,
    CallDisposition,
    CallSource,
    InstallationStatus,
    UserRole,
)
from src.core.phone import phone_key
from src.modules.audit.models import AuditLogModel
from src.modules.calls.models import CallModel
from src.modules.devices.models import CallLogDeltaModel
from src.modules.numbers.models import NumberAssignmentModel

pytestmark = pytest.mark.asyncio

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "contract" / "phone-vectors.json").read_text()
)

NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


async def test_required_extensions_are_installed(db) -> None:
    """``btree_gist`` missing means the exclusion constraint never got created."""
    rows = await db.execute(sa.text("SELECT extname FROM pg_extension"))
    installed = {name for (name,) in rows}
    assert {"btree_gist", "citext"} <= installed


async def test_every_spec_table_exists(db) -> None:
    rows = await db.execute(
        sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )
    tables = {name for (name,) in rows}
    expected = {
        "agents", "alerts", "app_settings", "app_versions", "audio_upload_sessions",
        "audit_log", "call_audio", "call_log_deltas", "callback_events",
        "callback_receivers", "calls", "capability_states", "capability_transitions",
        "commands", "data_usage_daily", "device_health", "devices",
        "enrolment_attempts", "enrolment_codes", "installations",
        "line_directory_entries", "model_capture_stats", "number_assignments",
        "number_verifications", "refresh_tokens", "registered_numbers",
        "service_tokens", "storage_usage_daily", "supported_models", "users",
    }
    assert expected <= tables
    assert len(expected) == 30


# --- The identity anchor ----------------------------------------------------


async def test_overlapping_assignments_fail_in_the_database(
    db, agent_factory, registered_number_factory, user_factory
) -> None:
    """Two admins cannot fork the identity anchor (UC-07, R18).

    This is the assertion T147 exists for: an application-level check loses to
    two concurrent requests, so the refusal must come from PostgreSQL.
    """
    admin_user = await user_factory(UserRole.ADMIN)
    first = await agent_factory()
    second = await agent_factory()
    number = await registered_number_factory(agent=first, created_by=admin_user)

    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=second.id,
            valid_from=NOW,
            created_by=admin_user.id,
        )
    )
    with pytest.raises(IntegrityError) as caught:
        await db.flush()
    assert "number_assignment_no_overlap" in str(caught.value)
    await db.rollback()


async def test_adjacent_assignments_are_allowed(
    db, agent_factory, registered_number_factory, user_factory
) -> None:
    """A handover is a closed period followed by an open one — the normal case."""
    admin_user = await user_factory(UserRole.ADMIN)
    first = await agent_factory()
    second = await agent_factory()
    number = await registered_number_factory()

    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=first.id,
            valid_from=NOW - timedelta(days=30),
            valid_to=NOW,
            created_by=admin_user.id,
        )
    )
    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=second.id,
            valid_from=NOW,
            created_by=admin_user.id,
        )
    )
    await db.flush()


async def test_valid_to_must_follow_valid_from(
    db, agent_factory, registered_number_factory, user_factory
) -> None:
    admin_user = await user_factory(UserRole.ADMIN)
    agent = await agent_factory()
    number = await registered_number_factory()
    db.add(
        NumberAssignmentModel(
            number_id=number.id,
            agent_id=agent.id,
            valid_from=NOW,
            valid_to=NOW - timedelta(days=1),
            created_by=admin_user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_one_active_installation_per_number(
    db, installation_factory, registered_number_factory, agent_factory
) -> None:
    """"The app is on two phones" doubles every call — a data-integrity failure."""
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent)
    await installation_factory(agent=agent, number=number)
    with pytest.raises(IntegrityError) as caught:
        await installation_factory(agent=agent, number=number)
    assert "uq_installation_active_per_number" in str(caught.value)
    await db.rollback()


async def test_a_replaced_installation_may_coexist(
    db, installation_factory, registered_number_factory, agent_factory
) -> None:
    """The partial index is on ``status = 'active'``: rebinding must stay possible."""
    agent = await agent_factory()
    number = await registered_number_factory(agent=agent)
    await installation_factory(
        agent=agent, number=number, status=InstallationStatus.REPLACED
    )
    await installation_factory(agent=agent, number=number)


async def test_a_sales_user_must_point_at_an_agent(db) -> None:
    """Own-scope narrowing has nothing to narrow on otherwise (SPEC §3.2)."""
    from src.modules.users.models import UserModel

    db.add(
        UserModel(
            email="orphan-sales@bonvi.uz",
            password_hash="x" * 64,
            full_name="Orphan",
            role=UserRole.SALES,
        )
    )
    with pytest.raises(IntegrityError) as caught:
        await db.flush()
    assert "sales_user_requires_agent" in str(caught.value)
    await db.rollback()


async def test_email_is_case_insensitive(db, user_factory) -> None:
    """CITEXT: 'Aziz@bonvi.uz' and 'aziz@bonvi.uz' are one account."""
    from src.modules.users.models import UserModel

    await user_factory(UserRole.ADMIN, email="Aziz@bonvi.uz")
    db.add(
        UserModel(
            email="aziz@bonvi.uz",
            password_hash="x" * 64,
            full_name="Impostor",
            role=UserRole.ADMIN,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


# --- The generated last-9 key columns ---------------------------------------


async def test_generated_key_agrees_with_python_for_every_vector(
    db, call_factory
) -> None:
    """The Python rule and the SQL rule must never disagree (§7).

    If they do, every join on the key silently returns nothing: no error, no
    rows, no clue. The vectors are the same file the Android suite reads.
    """
    for vector in VECTORS["vectors"]:
        call = await call_factory(remote_number=vector["raw"])
        assert call.remote_number_key == phone_key(vector["raw"]), vector["note"]


async def test_registered_number_key_is_unique_across_formats(
    db, registered_number_factory
) -> None:
    """A number typed in three formats is one row (N37)."""
    from src.modules.numbers.models import RegisteredNumberModel

    number = await registered_number_factory(e164="+998901112233")
    assert number.phone_key == "901112233"
    db.add(RegisteredNumberModel(e164="998 90 111 22 33"))
    with pytest.raises(IntegrityError) as caught:
        await db.flush()
    assert "phone_key" in str(caught.value)
    await db.rollback()


async def test_call_log_delta_is_generated(db, installation_factory) -> None:
    installation = await installation_factory()
    delta = CallLogDeltaModel(
        installation_id=installation.id,
        number_id=installation.number_id,
        period_date=NOW.date(),
        device_counted=31,
        uploaded_count=30,
        subscription_unknown_count=2,
    )
    db.add(delta)
    await db.flush()
    await db.refresh(delta)
    assert delta.delta == 1


# --- The four calls CHECK constraints ---------------------------------------


async def _reject(db, call: CallModel, constraint: str) -> None:
    db.add(call)
    with pytest.raises(IntegrityError) as caught:
        await db.flush()
    assert constraint in str(caught.value)
    await db.rollback()


def _base_call(installation, **overrides) -> CallModel:
    values = {
        "client_call_id": uuid.uuid4(),
        "installation_id": installation.id,
        "number_id": installation.number_id,
        "agent_id": installation.agent_id,
        "direction": CallDirection.OUTGOING,
        "disposition": CallDisposition.ANSWERED,
        "started_at": NOW,
        "answered_at": NOW + timedelta(seconds=5),
        "ended_at": NOW + timedelta(seconds=65),
        "duration_sec": 60,
        "device_epoch_ms": int(NOW.timestamp() * 1000),
        "device_timezone": "Asia/Tashkent",
        "source": CallSource.LIVE_CAPTURE,
        "has_audio": True,
        "audio_missing_reason": None,
        "app_version": "1.0.0",
        "app_variant": AppVariant.MODERN34,
    }
    values.update(overrides)
    return CallModel(**values)


async def test_audio_less_call_without_a_reason_is_rejected(
    db, installation_factory
) -> None:
    """N5: "100 % of calls carry a reason" is a constraint, not a convention."""
    installation = await installation_factory()
    await _reject(
        db,
        _base_call(installation, has_audio=False, audio_missing_reason=None),
        "ck_calls_audio_reason_present",
    )


async def test_call_with_audio_and_a_reason_is_rejected(
    db, installation_factory
) -> None:
    from src.core.enums import AudioMissingReason

    installation = await installation_factory()
    await _reject(
        db,
        _base_call(
            installation,
            has_audio=True,
            audio_missing_reason=AudioMissingReason.NO_PERMISSION,
        ),
        "ck_calls_audio_reason_present",
    )


async def test_incoming_no_answer_is_unrepresentable(db, installation_factory) -> None:
    """UC-11: ``no_answer`` is outgoing-only."""
    installation = await installation_factory()
    await _reject(
        db,
        _base_call(
            installation,
            direction=CallDirection.INCOMING,
            disposition=CallDisposition.NO_ANSWER,
            answered_at=None,
            duration_sec=0,
        ),
        "ck_calls_direction_disposition",
    )


async def test_outgoing_missed_is_unrepresentable(db, installation_factory) -> None:
    """``missed`` and ``rejected`` are incoming-only."""
    installation = await installation_factory()
    await _reject(
        db,
        _base_call(
            installation,
            direction=CallDirection.OUTGOING,
            disposition=CallDisposition.MISSED,
            answered_at=None,
            duration_sec=0,
        ),
        "ck_calls_direction_disposition",
    )


async def test_answered_without_answered_at_is_rejected(db, installation_factory) -> None:
    """UC-09: "answered" and "there is an answered_at" are the same fact."""
    installation = await installation_factory()
    await _reject(
        db, _base_call(installation, answered_at=None), "ck_calls_answered_has_timestamp"
    )


async def test_unanswered_with_an_answered_at_is_rejected(
    db, installation_factory
) -> None:
    installation = await installation_factory()
    await _reject(
        db,
        _base_call(
            installation,
            direction=CallDirection.OUTGOING,
            disposition=CallDisposition.NO_ANSWER,
            duration_sec=0,
        ),
        "ck_calls_answered_has_timestamp",
    )


async def test_answered_with_zero_duration_is_rejected(db, installation_factory) -> None:
    """UC-09/UC-11: zero calls classified answered that the log shows as 0 s."""
    installation = await installation_factory()
    await _reject(
        db, _base_call(installation, duration_sec=0), "ck_calls_answered_has_duration"
    )


async def test_unanswered_with_a_duration_is_rejected(db, installation_factory) -> None:
    """The other half of SPEC §3.5's duration rule, in the same constraint."""
    installation = await installation_factory()
    await _reject(
        db,
        _base_call(
            installation,
            direction=CallDirection.OUTGOING,
            disposition=CallDisposition.NO_ANSWER,
            answered_at=None,
            duration_sec=42,
        ),
        "ck_calls_answered_has_duration",
    )


async def test_client_call_id_is_unique(db, call_factory) -> None:
    """The idempotency key. Duplicate rate must be 0 (N2)."""
    first = await call_factory()
    with pytest.raises(IntegrityError):
        await call_factory(client_call_id=first.client_call_id)
    await db.rollback()


async def test_seq_is_assigned_by_the_database(db, call_factory) -> None:
    """The export cursor is server-generated; a client cannot mint one."""
    first = await call_factory()
    second = await call_factory()
    assert first.seq is not None and second.seq > first.seq


# --- The audit log is append-only -------------------------------------------


async def _audit_row(db) -> AuditLogModel:
    row = AuditLogModel(
        actor_type=ActorType.SYSTEM,
        action=AuditAction.SETTING_UPDATED,
        object_type="app_settings",
    )
    db.add(row)
    await db.flush()
    return row


async def test_audit_rows_cannot_be_updated(db) -> None:
    """UC-24/N27: enforced by the database, so no code path can bypass it."""
    row = await _audit_row(db)
    with pytest.raises(DBAPIError) as caught:
        await db.execute(
            sa.update(AuditLogModel)
            .where(AuditLogModel.id == row.id)
            .values(object_type="tampered")
        )
    assert "append-only" in str(caught.value)
    await db.rollback()


async def test_audit_rows_cannot_be_deleted(db) -> None:
    row = await _audit_row(db)
    with pytest.raises(DBAPIError) as caught:
        await db.execute(sa.delete(AuditLogModel).where(AuditLogModel.id == row.id))
    assert "append-only" in str(caught.value)
    await db.rollback()


# --- Seeded settings --------------------------------------------------------


async def test_every_settings_key_is_seeded_with_its_documented_default(db) -> None:
    """SPEC §3.8. A missing key must be a bug, not a silent ``None``."""
    expected = {
        "retention.audio_months": 12,
        "retention.confirm_below_months": 3,
        "retention.callback_events_days": 90,
        "alerts.device_offline_minutes": 10,
        "alerts.silence_hours": 4,
        "alerts.fleet_silence_hours": 2,
        "alerts.capture_regression_pp": 10,
        "alerts.email_to": [],
        "app.min_supported_version_code": 1,
        "upload.chunk_size_bytes": 524288,
        "upload.session_ttl_days": 7,
        "upload.max_chunk_bytes": 4194304,
        "data.cellular_cap_bytes_month": 1073741824,
        "data.deferred_daily_cap_bytes": 5242880,
        "audio.defer_to_wifi_hours": 24,
        "queue.max_records": 2000,
        "queue.max_audio_bytes": 1073741824,
        "queue.min_free_space_bytes": 1073741824,
        "device.heartbeat_seconds": 120,
        "device.capability_recheck_hours": 6,
        "device.call_log_sweep_hours": 6,
        "working_hours.start": "08:00",
        "working_hours.end": "20:00",
        "working_hours.timezone": "Asia/Tashkent",
        "working_hours.workdays": [1, 2, 3, 4, 5, 6],
        "working_hours.holidays": [],
        "enrolment.code_ttl_hours": 24,
        "enrolment.callback_window_seconds": 300,
        # Migration 006. On by default because the alternative default is a
        # fleet that cannot enrol: both proving routes are frequently
        # unavailable at once on these handsets.
        "enrolment.allow_self_declared": True,
    }
    rows = await db.execute(sa.text("SELECT key, value FROM app_settings"))
    seeded = {key: value for key, value in rows}
    assert seeded == expected
