"""Call ingest and query (T25, T46, T47; SPEC §3.10, §4.4, §4.7).

The two halves of this module answer different questions with different
timestamps, and conflating them is the mistake the SPEC calls out twice:

* **attribution and business dates use ``started_at``** — a call made before a
  SIM handover stays with agent A even if the old phone only comes online a
  week later (D-08);
* **ordering, cursors and retention use ``received_at``** — devices lie about
  time and users change it (N36).

Idempotency is ``core.idempotency.upsert_once``: one ``INSERT … ON CONFLICT DO
NOTHING RETURNING id``, never a ``SELECT`` followed by an ``INSERT``. The
forbidden shape double-inserts under exactly the retry storm this exists to
survive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.clock import TASHKENT
from src.core.deps import Principal
from src.core.enums import (
    AlertKind,
    AlertSeverity,
    AudioMissingReason,
    CallDisposition,
    CallType,
)
from src.core.errors import BadRequestError, ConflictError, ErrorCode, NotFoundError
from src.core.idempotency import upsert_once
from src.core.logging import get_logger
from src.core.pagination import Cursor, Page, apply_keyset
from src.core.permissions import Perm
from src.core.phone import phone_key, to_e164
from src.core.sqltext import escape_like
from src.modules.agents.models import AgentModel
from src.modules.alerts.service import AlertService
from src.modules.audio.service import AudioService
from src.modules.calls.models import CallModel
from src.modules.calls.rules import (
    LineDirectory,
    classify_call_type,
    clock_skew_seconds,
    resolve_audio_reason,
)
from src.modules.calls.schemas import (
    CallAudioSummary,
    CallFilters,
    CallResponse,
    DeviceCallIn,
    DeviceCallResultOut,
)
from src.modules.catalog.service import CatalogService
from src.modules.devices.service import DeviceService
from src.modules.installations.models import InstallationModel
from src.modules.numbers.models import NumberAssignmentModel
from src.modules.numbers.service import NumberService

log = get_logger(__name__)

#: Fields the device may correct on a later upload (SPEC §3.10 rule 6).
#: Everything else — number_id, agent_id, installation_id, received_at, seq —
#: is immutable after first write, because a device must not be able to move a
#: call to another agent by re-sending it.
MUTABLE_FIELDS = frozenset(
    {
        "direction",
        "disposition",
        "started_at",
        "answered_at",
        "ended_at",
        "duration_sec",
        "ring_sec",
        "contact_name",
        "remote_number",
        "reconciled_with_call_log",
        "audio_missing_reason",
        "source",
    }
)


@dataclass(frozen=True)
class Attribution:
    """Who a call belongs to, and which assignment decided that."""

    agent_id: uuid.UUID
    assignment_id: uuid.UUID | None
    out_of_range: bool


class CallService:
    """Ingest, list and read calls. Owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.alerts = AlertService(session)
        self.numbers = NumberService(session)
        self.catalog = CatalogService(session)

    # --- Ingest (device) --------------------------------------------------

    async def ingest(
        self, installation: InstallationModel, items: list[DeviceCallIn]
    ) -> list[DeviceCallResultOut]:
        """Upsert a batch. One transaction, one result per item."""
        directory = await self._line_directory()
        results: list[DeviceCallResultOut] = []
        for item in items:
            try:
                results.append(await self._ingest_one(installation, item, directory))
            except ConflictError as exc:
                # Per-item failure. The rest of the batch still commits: a
                # batch that fails wholesale is a batch the device retries
                # forever (SPEC §4.4 rule 6).
                results.append(
                    DeviceCallResultOut(
                        client_call_id=item.client_call_id,
                        status="failed",
                        error={"code": exc.code, "message": exc.message or exc.code},
                    )
                )
        await self.session.commit()
        return results

    async def _ingest_one(
        self,
        installation: InstallationModel,
        item: DeviceCallIn,
        directory: LineDirectory,
    ) -> DeviceCallResultOut:
        existing = await self.session.scalar(
            select(CallModel).where(CallModel.client_call_id == item.client_call_id)
        )
        if existing is not None:
            return await self._apply_correction(existing, item, installation)

        attribution = await self._attribute(installation, item.started_at)
        received_at = clock.now()
        skew = clock_skew_seconds(
            int(received_at.timestamp() * 1000), item.device_epoch_ms, item.device_rtt_ms
        )
        reason = resolve_audio_reason(
            disposition=item.disposition.value,
            audio_expected=item.audio_expected,
            client_reason=item.audio_missing_reason.value
            if item.audio_missing_reason
            else None,
        )
        values = {
            "id": uuid.uuid4(),
            "client_call_id": item.client_call_id,
            "installation_id": installation.id,
            # Resolved from the installation, never from the payload: the
            # device does not get to say which number it is (SPEC §4.4 rule 2).
            "number_id": installation.number_id,
            "agent_id": attribution.agent_id,
            "assignment_id": attribution.assignment_id,
            "direction": item.direction,
            "disposition": item.disposition,
            "remote_number": _normalise_remote(item.remote_number),
            "contact_name": item.contact_name,
            "call_type": CallType(classify_call_type(item.remote_number, directory)),
            "started_at": item.started_at,
            "answered_at": item.answered_at,
            "ended_at": item.ended_at,
            "duration_sec": item.duration_sec,
            "ring_sec": item.ring_sec,
            "device_epoch_ms": item.device_epoch_ms,
            "device_timezone": item.device_timezone,
            "clock_skew_sec": skew,
            "received_at": received_at,
            "sim_subscription_id": item.sim_subscription_id,
            "sim_slot": item.sim_slot,
            "source": item.source,
            "reconciled_with_call_log": item.reconciled_with_call_log,
            "command_id": item.command_id,
            "has_audio": False,
            "audio_missing_reason": AudioMissingReason(reason) if reason else None,
            "app_version": item.app_version or installation.app_version or "unknown",
            "app_variant": item.app_variant or installation.app_variant,
        }
        call_id, created = await upsert_once(
            self.session, CallModel, "client_call_id", values
        )
        if attribution.out_of_range:
            await self._raise_out_of_range(installation, item.started_at)
        return DeviceCallResultOut(
            client_call_id=item.client_call_id,
            id=call_id,
            status="created" if created else "unchanged",
            audio_upload=_audio_upload_state(item, has_audio=False),
        )

    async def _apply_correction(
        self, call: CallModel, item: DeviceCallIn, installation: InstallationModel
    ) -> DeviceCallResultOut:
        """A repeat of a known ``client_call_id`` (SPEC §3.10 rules 4 and 5)."""
        if call.number_id != installation.number_id:
            # Two devices claiming one call is either a bug or a stolen
            # credential. Both need a human, and nothing is written either way.
            await self.alerts.raise_alert(
                kind=AlertKind.CREDENTIAL_REPLAY,
                severity=AlertSeverity.CRITICAL,
                scope=installation.id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                detail={"client_call_id": str(item.client_call_id)},
            )
            log.warning(
                "call_identity_conflict",
                installation_id=str(installation.id),
                call_id=str(call.id),
            )
            raise ConflictError(ErrorCode.CALL_IDENTITY_CONFLICT)

        changed = False
        for field in MUTABLE_FIELDS:
            if not hasattr(item, field):
                continue
            new_value = getattr(item, field)
            if field == "remote_number":
                new_value = _normalise_remote(new_value)
            if field == "audio_missing_reason" and new_value is None:
                # The device omitting a reason is not the device clearing one.
                continue
            if new_value is not None and getattr(call, field) != new_value:
                setattr(call, field, new_value)
                changed = True
        await self.session.flush()
        return DeviceCallResultOut(
            client_call_id=item.client_call_id,
            id=call.id,
            status="updated" if changed else "unchanged",
            audio_upload=_audio_upload_state(item, has_audio=call.has_audio),
        )

    async def _attribute(
        self, installation: InstallationModel, started_at: datetime
    ) -> Attribution:
        """Find the assignment covering ``started_at`` (SPEC §3.3, D-08)."""
        assignment = await self._assignment_at(installation.number_id, started_at)
        if assignment is not None:
            return Attribution(assignment.agent_id, assignment.id, out_of_range=False)

        # Nothing covers the call's own start. Dropping the call would be worse
        # than attributing it imperfectly, so fall back to the assignment in
        # force when the phone was bound and say so out loud (SPEC §4.4 rule 2).
        fallback = None
        if installation.bound_at is not None:
            fallback = await self._assignment_at(
                installation.number_id, installation.bound_at
            )
        if fallback is not None:
            return Attribution(fallback.agent_id, fallback.id, out_of_range=True)
        return Attribution(installation.agent_id, None, out_of_range=True)

    async def _assignment_at(
        self, number_id: uuid.UUID, moment: datetime
    ) -> NumberAssignmentModel | None:
        """The attribution rule (D-08) lives in ``numbers``; this asks it."""
        return await self.numbers.holder_at(number_id, moment)

    async def _raise_out_of_range(
        self, installation: InstallationModel, started_at: datetime
    ) -> None:
        await self.alerts.raise_alert(
            kind=AlertKind.ATTRIBUTION_OUT_OF_RANGE,
            severity=AlertSeverity.INFO,
            scope=installation.id,
            installation_id=installation.id,
            agent_id=installation.agent_id,
            number_id=installation.number_id,
            detail={"started_at": started_at.isoformat()},
        )

    async def _line_directory(self) -> LineDirectory:
        """Assemble the directory: every registered number plus admin extras.

        The registered half is **computed, never copied** into
        ``line_directory_entries``. Copying it is how BonviZvonki's directory
        starved (UC-25, L5).
        """
        buckets: dict[str, set[str]] = {"exact": set(), "prefix": set(), "suffix": set()}
        for kind, digits in await self.catalog.directory_rules():
            buckets[kind].add(digits)
        return LineDirectory(
            registered_keys=await self.numbers.all_phone_keys(),
            exact=frozenset(buckets["exact"]),
            prefix=frozenset(buckets["prefix"]),
            suffix=frozenset(buckets["suffix"]),
        )

    # --- Query (panel) ----------------------------------------------------

    def _filtered(self, principal: Principal, filters: CallFilters | None) -> Select:
        """One filter builder, used by the list **and** by the export.

        UC-22 requires the export's row count to equal the count on screen for
        the same filter. The only way to be sure of that is for there to be one
        implementation, so a parallel one is forbidden rather than discouraged.
        """
        statement = self._scoped(select(CallModel), principal)
        if filters is None:
            return statement

        if filters.agent_id:
            statement = statement.where(CallModel.agent_id.in_(filters.agent_id))
        if filters.number_id:
            statement = statement.where(CallModel.number_id.in_(filters.number_id))
        if filters.installation_id is not None:
            statement = statement.where(
                CallModel.installation_id == filters.installation_id
            )
        if filters.direction is not None:
            statement = statement.where(CallModel.direction == filters.direction)
        if filters.disposition is not None:
            statement = statement.where(CallModel.disposition == filters.disposition)
        if filters.call_type is not None:
            statement = statement.where(CallModel.call_type == filters.call_type)
        if filters.has_audio is not None:
            statement = statement.where(CallModel.has_audio.is_(filters.has_audio))
        if filters.audio_missing_reason:
            statement = statement.where(
                CallModel.audio_missing_reason.in_(filters.audio_missing_reason)
            )
        if filters.app_variant is not None:
            statement = statement.where(CallModel.app_variant == filters.app_variant)
        if filters.min_duration_sec is not None:
            statement = statement.where(
                CallModel.duration_sec >= filters.min_duration_sec
            )
        if filters.max_duration_sec is not None:
            statement = statement.where(
                CallModel.duration_sec <= filters.max_duration_sec
            )
        if filters.remote_number is not None:
            # Matched on the key, so "+998 93 555-44-33" and "935554433" find
            # the same calls (N37).
            key = phone_key(filters.remote_number)
            statement = statement.where(
                CallModel.remote_number_key == key
                if key
                else CallModel.remote_number == filters.remote_number
            )
        if filters.q:
            statement = statement.where(
                CallModel.contact_name.ilike(f"%{escape_like(filters.q)}%")
            )
        # Business dates are Asia/Tashkent calendar days against started_at,
        # not received_at: a call made yesterday and uploaded today belongs to
        # yesterday (D-08).
        if filters.date_from is not None:
            statement = statement.where(
                CallModel.started_at
                >= datetime.combine(filters.date_from, time.min, tzinfo=TASHKENT)
            )
        if filters.date_to is not None:
            statement = statement.where(
                CallModel.started_at
                < datetime.combine(filters.date_to, time.min, tzinfo=TASHKENT)
                + timedelta(days=1)
            )
        return statement

    #: SPEC §4.7's sort options. Every one pairs with ``id``, or paging
    #: duplicates rows whose sort values tie.
    SORT_COLUMNS = {
        "received_at": CallModel.received_at,
        "started_at": CallModel.started_at,
        "duration_sec": CallModel.duration_sec,
    }

    async def list(
        self,
        principal: Principal,
        limit: int,
        cursor: Cursor | None = None,
        with_total: bool = False,
        filters: CallFilters | None = None,
        sort: str = "received_at",
        order: str = "desc",
    ) -> Page[CallResponse]:
        """A cursor page, ordered by ``received_at DESC, id DESC``.

        Own-scope is applied here and only here: ``calls:read:own`` gets a
        salesperson past the router dependency, and this query is what narrows
        the rows (SPEC §4.1 rule 1). A second permission check would put a
        business rule in the router.
        """
        sort_column = self.SORT_COLUMNS.get(sort)
        if sort_column is None:
            raise BadRequestError(ErrorCode.BAD_REQUEST, detail={"field": "sort"})
        statement = self._filtered(principal, filters)

        total = None
        if with_total:
            total = await self.session.scalar(
                select(func.count()).select_from(statement.subquery())
            )

        paged = apply_keyset(
            statement, sort_column, CallModel.id, cursor, descending=order != "asc"
        ).limit(limit + 1)
        rows = list((await self.session.scalars(paged)).all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            Cursor(getattr(rows[-1], sort), rows[-1].id).encode()
            if has_more and rows
            else None
        )
        return Page(
            items=await self.views(rows),
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
        )

    async def views(self, calls: list[CallModel]) -> list[CallResponse]:
        """Attach the display fields and the audio summary, in two queries.

        Two, not two-per-row: an agent name per row is the N+1 problem, and
        moving it to the browser only changes whose problem it is. The device
        model comes from ``DeviceService`` rather than a join, because ``calls``
        has no foreign key into ``devices`` and §2 says arrows follow keys.
        """
        if not calls:
            return []
        names = await self._display_names([call.agent_id for call in calls])
        numbers = await self.numbers.e164_map([call.number_id for call in calls])
        models = await DeviceService(self.session).models_for_installations(
            [call.installation_id for call in calls]
        )
        summaries = await AudioService(self.session).summaries_for(
            [call.id for call in calls]
        )
        return [
            CallResponse(
                **{
                    field: getattr(call, field)
                    for field in CallResponse.model_fields
                    if hasattr(call, field)
                },
                agent_name=names.get(call.agent_id, ""),
                number_e164=numbers.get(call.number_id, ""),
                device_model=models.get(call.installation_id),
                audio=summaries.get(call.id)
                or CallAudioSummary(
                    available=False, audio_missing_reason=call.audio_missing_reason
                ),
            )
            for call in calls
        ]

    async def view(self, call: CallModel) -> CallResponse:
        """One call, enriched the same way as a list row."""
        return (await self.views([call]))[0]

    async def _display_names(self, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        rows = (
            await self.session.execute(
                select(AgentModel.id, AgentModel.full_name).where(
                    AgentModel.id.in_(set(agent_ids))
                )
            )
        ).all()
        return {row.id: row.full_name for row in rows}

    async def count(self, principal: Principal, filters: CallFilters | None) -> int:
        """The number the panel shows, and the number the export must produce."""
        return await self.session.scalar(
            select(func.count()).select_from(
                self._filtered(principal, filters).subquery()
            )
        )

    async def stream_export(self, principal: Principal, filters: CallFilters | None):
        """Rows for the CSV export, oldest first, streamed (T48, UC-22).

        A server-side cursor, not ``fetchall``: 50,000 rows must arrive in
        under 30 seconds without the process holding them all.
        """
        statement = self._filtered(principal, filters).order_by(
            CallModel.started_at.asc(), CallModel.id.asc()
        )
        result = await self.session.stream(statement)
        async for row in result.scalars():
            yield row

    async def reclassify(self) -> int:
        """Recompute ``call_type`` after the directory changed (T49).

        Recomputed rather than left alone because UC-25's answer depends on a
        table an admin edits: a number that becomes internal today was internal
        yesterday too, and a report that says otherwise is wrong.
        """
        directory = await self._line_directory()
        updated = 0
        result = await self.session.stream(select(CallModel))
        async for call in result.scalars():
            new_type = CallType(classify_call_type(call.remote_number, directory))
            if call.call_type is not new_type:
                call.call_type = new_type
                updated += 1
        await self.session.commit()
        return updated

    async def get(self, principal: Principal, call_id: uuid.UUID) -> CallModel:
        """One call. **Wrong owner is 404, not 403** (UC-21, SPEC §4.1 rule 2).

        403 would confirm the row exists, which tells a salesperson that a
        colleague spoke to a given number.
        """
        call = await self.session.scalar(
            self._scoped(select(CallModel), principal).where(CallModel.id == call_id)
        )
        if call is None:
            raise NotFoundError(ErrorCode.CALL_NOT_FOUND)
        return call

    async def set_note(
        self, principal: Principal, call_id: uuid.UUID, note: str | None
    ) -> CallModel:
        call = await self.get(principal, call_id)
        call.note = note
        await self.session.commit()
        return call

    #: Permissions that see every call. ``export:*`` is here because the
    #: machine export is fleet-wide by contract (UC-29): a service token has no
    #: agent to be narrowed to, and narrowing it to ``None`` would silently
    #: return an empty export rather than an error.
    FLEET_WIDE = (
        Perm.CALLS_READ,
        Perm.AUDIO_PLAY,
        Perm.EXPORT_READ,
        Perm.EXPORT_AUDIO,
    )

    def _scoped(self, statement: Select, principal: Principal) -> Select:
        """Narrow to the principal's own agent when they only hold ``:own``."""
        if principal.has_any(*self.FLEET_WIDE):
            return statement
        # A sales principal with no linked agent sees nothing rather than
        # everything: the database CHECK makes that state unreachable, and this
        # is the belt to its braces.
        return statement.where(CallModel.agent_id == principal.agent_id)


def _normalise_remote(raw: str | None) -> str | None:
    """E.164 where we can parse it, the raw string where we cannot.

    Losing a call because its number was odd is worse than storing an unkeyed
    row — the generated ``remote_number_key`` column simply stays NULL
    (SPEC §4.0).
    """
    if raw is None:
        return None
    if phone_key(raw) is None:
        return raw[:32]
    return to_e164(raw)


def _audio_upload_state(item: DeviceCallIn, has_audio: bool) -> str:
    if has_audio:
        return "already_present"
    if item.disposition is not CallDisposition.ANSWERED or not item.audio_expected:
        return "not_expected"
    return "required"
