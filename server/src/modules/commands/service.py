"""Click-to-call and the other device commands (T55, UC-16).

**No call row is ever linked to a failed command.** A partial unique index on
``calls.command_id`` stops two calls claiming one command; this service stops a
call being linked to a command that was never acknowledged. Both are needed:
the index catches the race, this catches the logic.

``latency_ms`` is stored on every acknowledgement so UC-16's five-second bar is
measured rather than assumed. ``RISKS.md`` R3 flags that bar as possibly
unachievable on doze-restricted OEMs, and this column is what makes the
conversation evidential instead of anecdotal.

The transport is the socket plus an FCM wake-up (SPEC §4.6). The lifecycle
does not depend on which one delivered the command — that is why it was built
and tested before the socket existed, and why :meth:`CommandService.deliver`
can be a thin choice between two transports rather than a second lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock, push, realtime
from src.core.enums import (
    ActorType,
    AuditAction,
    CommandFailureReason,
    CommandKind,
    CommandStatus,
)
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.core.logging import get_logger
from src.core.phone import to_e164
from src.modules.audit.service import AuditService
from src.modules.calls.models import CallModel
from src.modules.commands.models import CommandModel
from src.modules.commands.schemas import (
    CommandFrameOut,
    CreateCommandRequest,
    DeviceAckIn,
)
from src.modules.installations.models import InstallationModel

log = get_logger(__name__)

#: UC-16: a dial older than two minutes must never ring. The app discards an
#: expired command on arrival as well, so a phone that wakes after three
#: minutes does nothing.
DIAL_TTL_SECONDS = 120
CONFIG_TTL_HOURS = 24

#: SPEC §4.6: no acknowledgement in fifteen seconds and the command failed.
ACK_TIMEOUT_SECONDS = 15


class CommandService:
    """The command lifecycle: issue, collect, acknowledge, expire."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def issue(
        self,
        installation_id: uuid.UUID,
        payload: CreateCommandRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> CommandModel:
        """Create a pending command for a phone.

        Issuing one is a person reaching into an employee's **personally
        owned** handset — the only action in the product that acts on somebody
        else's hardware — so it is audited under its own action rather than
        buried in a generic one.
        """
        installation = await self.session.get(InstallationModel, installation_id)
        if installation is None:
            raise NotFoundError()

        if payload.kind is CommandKind.DIAL:
            if not payload.number:
                raise ConflictError(ErrorCode.BAD_REQUEST, detail={"field": "number"})
            body = {"number": to_e164(payload.number) or payload.number}
            ttl = timedelta(seconds=DIAL_TTL_SECONDS)
        else:
            body = {}
            ttl = timedelta(hours=CONFIG_TTL_HOURS)

        command = CommandModel(
            installation_id=installation_id,
            kind=payload.kind,
            payload=body or None,
            created_by=actor_id,
            status=CommandStatus.PENDING,
            expires_at=clock.now() + ttl,
        )
        self.session.add(command)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.COMMAND_ISSUED,
            object_type="commands",
            object_id=command.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={
                "kind": payload.kind.value,
                "installation_id": str(installation_id),
                "agent_id": str(installation.agent_id),
                "reason": payload.reason,
            },
        )
        await self.session.commit()
        log.info("command_issued", command_id=str(command.id), kind=payload.kind.value)
        return command

    async def issue_and_deliver(
        self,
        installation_id: uuid.UUID,
        payload: CreateCommandRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> CommandModel:
        """One panel click, end to end. The router calls this and nothing else.

        Issuing and delivering are separate methods because a resend is a real
        operation and because the lifecycle was built before the transport
        existed. They are joined *here* rather than in the handler so the
        orchestration and the commit stay in the service (§2) — the same shape
        as ``DeviceService.ingest_heartbeat``.
        """
        command = await self.issue(installation_id, payload, actor_id, ip)
        await self.deliver(command)
        return command

    async def deliver(self, command: CommandModel) -> bool:
        """Get ``command`` to the phone now, or arrange for it to come and look.

        Returns whether it went down a **live socket**. That is the only case
        with a chance at UC-16's five-second bar, so it is the thing worth
        reporting; everything else is a wake-up and a wait.

        Order matters. The socket is tried first because it is the fast path and
        because it is the one we control. Only when there is no socket does the
        FCM wake-up happen, and that message carries ``{"cmd":"poll"}`` and
        never the number being dialled (SPEC §4.6, and see ``core/push.py`` for
        why the interface cannot express anything else).

        A wake-up is not a delivery. ``sent_at`` is set either way — the fifteen
        second ack clock starts when we stopped being able to do anything more —
        but a phone that never answers ends up ``failed`` /``device_offline``
        through :meth:`expire_stale`, which is the truthful outcome whether the
        socket was down or FCM never reached it.
        """
        frame = CommandFrameOut(
            command_id=command.id,
            kind=command.kind,
            number=(command.payload or {}).get("number"),
            issued_at=command.created_at,
            expires_at=command.expires_at,
        )
        on_socket = await realtime.get_hub().send(
            command.installation_id, frame.model_dump(mode="json")
        )
        if not on_socket:
            # No registration token is stored anywhere yet, so this reports
            # "cannot wake" today rather than pretending. See
            # docs/PENDING_WIRING.md — the column and the wire field are the
            # missing halves, not this call site.
            try:
                await push.get_sender().wake(command.installation_id, push_token=None)
            except Exception:  # noqa: BLE001 — a future FCM sender calls a network
                # The command is already recorded, and a phone we failed to wake
                # is one that does not answer, which ``expire_stale`` already
                # calls ``device_offline``. An outage at Google must not turn a
                # click-to-call into a 500 on the panel.
                log.warning("push_wake_failed", command_id=str(command.id))

        command.status = CommandStatus.SENT
        command.sent_at = command.sent_at or clock.now()
        await self.session.commit()
        log.info(
            "command_delivered",
            command_id=str(command.id),
            kind=command.kind.value,
            transport="socket" if on_socket else "push",
        )
        return on_socket

    async def pending_for(self, installation: InstallationModel) -> list[CommandModel]:
        """Commands the phone should act on now, marked as sent.

        Anything already past ``expires_at`` is expired rather than handed
        over: a dial that arrives three minutes late must not ring (UC-16).
        """
        moment = clock.now()
        rows = list(
            (
                await self.session.scalars(
                    select(CommandModel).where(
                        CommandModel.installation_id == installation.id,
                        CommandModel.status.in_(
                            (CommandStatus.PENDING, CommandStatus.SENT)
                        ),
                    )
                )
            ).all()
        )
        live: list[CommandModel] = []
        for command in rows:
            if command.expires_at <= moment:
                command.status = CommandStatus.EXPIRED
                continue
            command.status = CommandStatus.SENT
            command.sent_at = command.sent_at or moment
            live.append(command)
        await self.session.commit()
        return live

    async def acknowledge(
        self, installation: InstallationModel, command_id: uuid.UUID, payload: DeviceAckIn
    ) -> CommandModel:
        """Record the device's answer and measure how long it took."""
        command = await self.session.get(CommandModel, command_id)
        if command is None or command.installation_id != installation.id:
            raise NotFoundError()

        moment = payload.at or clock.now()
        command.acked_at = moment
        command.latency_ms = max(
            int((moment - command.created_at).total_seconds() * 1000), 0
        )
        if payload.status == "acknowledged":
            command.status = CommandStatus.ACKNOWLEDGED
            if payload.result_client_call_id is not None:
                await self._link_call(command, payload.result_client_call_id)
        else:
            command.status = CommandStatus.FAILED
            command.failure_reason = (
                payload.failure_reason or CommandFailureReason.OS_REFUSED
            )
        await self.session.commit()
        return command

    async def _link_call(self, command: CommandModel, client_call_id: uuid.UUID) -> None:
        """Attach the resulting call — **only** to an acknowledged command.

        A failed command that carried a call id would mean the panel shows a
        dial that failed and a call that happened, which is a contradiction an
        admin cannot resolve.
        """
        if command.status is not CommandStatus.ACKNOWLEDGED:
            return
        call = await self.session.scalar(
            select(CallModel).where(CallModel.client_call_id == client_call_id)
        )
        if call is None:
            return
        call.command_id = command.id
        command.result_call_id = call.id

    async def expire_stale(self) -> int:
        """Fail commands with no acknowledgement, expire the rest (SPEC §4.6).

        A phone that never answered is ``device_offline``; the panel shows the
        reason, because "it did not work" without one is not actionable.
        """
        moment = clock.now()
        failed = 0
        rows = await self.session.scalars(
            select(CommandModel).where(
                CommandModel.status.in_((CommandStatus.PENDING, CommandStatus.SENT))
            )
        )
        for command in rows:
            sent = command.sent_at
            if sent is not None and (moment - sent).total_seconds() >= ACK_TIMEOUT_SECONDS:
                command.status = CommandStatus.FAILED
                command.failure_reason = CommandFailureReason.DEVICE_OFFLINE
                failed += 1
            elif command.expires_at <= moment:
                command.status = CommandStatus.EXPIRED
                failed += 1
        await self.session.commit()
        return failed

    async def get(self, command_id: uuid.UUID) -> CommandModel:
        command = await self.session.get(CommandModel, command_id)
        if command is None:
            raise NotFoundError()
        return command

    async def list_for(
        self, installation_id: uuid.UUID, limit: int = 50
    ) -> tuple[list[CommandModel], int]:
        rows = list(
            (
                await self.session.scalars(
                    select(CommandModel)
                    .where(CommandModel.installation_id == installation_id)
                    .order_by(CommandModel.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        return rows, len(rows)
