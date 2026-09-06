"""Installation lifecycle: bind, rebind, revoke, attest (T35, T142; UC-07, UC-08).

**Exactly one active installation per registered number**, enforced by a partial
unique index rather than by this code — "the app is on two phones" doubles every
call and is a data-integrity failure, not a UI problem.

Rebinding (UC-07) is deliberately gentle to the phone being replaced: it becomes
``replaced`` and **keeps working on ingest endpoints**, and is refused only on
``POST /auth/refresh`` once its queue has drained. Refusing an old binding must
never destroy the calls it is still holding — the same rule, for the same
reason, as the stale-version gate (SPEC §4.3, §9.3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.deps import Principal
from src.core.enums import (
    ActorType,
    AlertKind,
    AlertSeverity,
    AppVariant,
    AuditAction,
    FunnelStage,
    InstallationStatus,
    VerificationMethod,
)
from src.core.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnauthorizedError,
    VersionUnsupportedError,
)
from src.core.logging import get_logger
from src.core.messages_uz import message_for
from src.core.security import (
    create_access_token,
    new_opaque_token,
    sha256_hex,
)
from src.modules.agents.models import AgentModel
from src.modules.alerts.service import AlertService
from src.modules.audit.service import AuditService
from src.modules.catalog.service import CatalogService
from src.modules.devices.models import DeviceHealthModel, DeviceModel
from src.modules.devices.schemas import UpdateBlockOut
from src.modules.devices.service import DeviceService
from src.modules.installations.models import InstallationModel
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

#: SPEC §4.2: twelve hours, not fifteen minutes. A phone can be offline for a
#: day, and N25's requirement is that expiry never loses data — not that the
#: window is tiny. The panel's window is short because a browser is always
#: online; the handset's is not.
DEVICE_ACCESS_TOKEN_HOURS = 12

TOKEN_TYPE_DEVICE = "device"

SETTING_MIN_VERSION_CODE = "app.min_supported_version_code"


def _version_code(
    reported_code: int | None, app_version: str | None, current
) -> int:
    """The installed version code, or the closest honest guess.

    ``reported_code`` is what the phone actually said — stored at enrolment and
    refreshed from ``X-App-Version-Code`` — and it is used whenever we have it.

    The rest is the fallback for a row written before migration 003, and it is
    a *guess*: it concatenates the digits of the version string, so ``"1.0.0"``
    becomes ``100``. Keep it only as a fallback. It fails **open** — an
    unidentifiable client is treated as current, because refusing a client we
    cannot identify is the one outcome N34 forbids, and a phone refused in
    error stops reporting calls nobody can recover.
    """
    if reported_code is not None:
        return reported_code
    if app_version is None:
        return current.version_code if current is not None else 1
    digits = "".join(part for part in app_version.split(".") if part.isdigit())
    return int(digits) if digits else (current.version_code if current else 1)


@dataclass(frozen=True)
class DeviceTokenPair:
    """An installation-bound access token and the refresh token that renews it."""

    access_token: str
    refresh_token: str
    expires_in: int


class InstallationService:
    """Everything that changes an installation's status. Owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.alerts = AlertService(session)

    async def list(
        self,
        status: InstallationStatus | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> tuple[list[InstallationModel], int]:
        statement = select(InstallationModel).order_by(
            InstallationModel.funnel_changed_at.desc()
        )
        if status is not None:
            statement = statement.where(InstallationModel.status == status)
        if agent_id is not None:
            statement = statement.where(InstallationModel.agent_id == agent_id)
        rows = list((await self.session.scalars(statement)).all())
        return rows, len(rows)

    async def get(self, installation_id: uuid.UUID) -> InstallationModel:
        installation = await self.session.get(InstallationModel, installation_id)
        if installation is None:
            raise NotFoundError()
        return installation

    async def agent_names_for(self, installation_ids) -> dict:
        """``{installation_id: agent name}`` in one query.

        This module has the foreign key into ``agents``, so the join belongs
        here — ``devices`` reaches agents only through installations, and §2
        says the arrows follow the keys.
        """
        if not installation_ids:
            return {}
        rows = (
            await self.session.execute(
                select(InstallationModel.id, AgentModel.full_name)
                .join(AgentModel, AgentModel.id == InstallationModel.agent_id)
                .where(InstallationModel.id.in_(set(installation_ids)))
            )
        ).all()
        return {row.id: row.full_name for row in rows}

    async def get_optional(
        self, installation_id: uuid.UUID | None
    ) -> InstallationModel | None:
        """The row or ``None`` — for messages, not for decisions."""
        if installation_id is None:
            return None
        return await self.session.get(InstallationModel, installation_id)

    async def create_pending(
        self,
        number_id: uuid.UUID,
        agent_id: uuid.UUID,
        device_id: uuid.UUID,
        device_fingerprint_hash: str,
        app_version: str,
        app_variant: AppVariant,
        app_version_code: int | None = None,
        sim_subscription_id: int | None = None,
        sim_slot: int | None = None,
    ) -> InstallationModel:
        """A freshly redeemed installation, not yet verified.

        ``pending`` and not ``active``: the number is not bound to this phone
        until verification proves it holds it, and an unverified installation
        cannot upload a single call.
        """
        installation = InstallationModel(
            number_id=number_id,
            agent_id=agent_id,
            device_id=device_id,
            status=InstallationStatus.PENDING,
            credential_hash=sha256_hex(new_opaque_token()),
            device_fingerprint_hash=device_fingerprint_hash,
            app_version=app_version,
            app_version_code=app_version_code,
            app_variant=app_variant,
            sim_subscription_id=sim_subscription_id,
            sim_slot=sim_slot,
            bound_at=clock.now(),
            funnel_stage=FunnelStage.INSTALLED,
            funnel_changed_at=clock.now(),
        )
        self.session.add(installation)
        await self.session.flush()
        return installation

    async def update_block(self, installation: InstallationModel) -> UpdateBlockOut:
        """The ``update`` block every device response carries (SPEC §4.3).

        ``required`` says "you are below the minimum"; it does **not** refuse
        anything. The app keeps capturing and draining and blocks only new
        enrolment actions. The refusal happens on refresh, once the queue is
        empty — refusing first destroys data.
        """
        settings = SettingsService(self.session)
        minimum = await settings.get_int(SETTING_MIN_VERSION_CODE)
        current = await CatalogService(self.session).current_release(
            installation.app_variant
        )
        installed = _version_code(
            installation.app_version_code, installation.app_version, current
        )
        return UpdateBlockOut(
            required=installed < minimum,
            min_version_code=minimum,
            latest_version=current.version if current else None,
            latest_version_code=current.version_code if current else None,
            apk_url=(
                f"/api/v1/app/download/{current.version_code}" if current else None
            ),
            message_uz=message_for(ErrorCode.APP_VERSION_UNSUPPORTED),
        )

    async def queue_is_drained(self, installation: InstallationModel) -> bool:
        """N34's precondition: the phone has reported an empty queue.

        A device that has never reported is **not** drained. Refusing a client
        whose backlog we have never seen is exactly the data loss the gate
        exists to avoid.
        """
        return await DeviceService(self.session).queue_is_empty(installation.id)

    # --- Installation-bound tokens (N24) ----------------------------------

    async def issue_device_pair(
        self, installation: InstallationModel
    ) -> DeviceTokenPair:
        """Mint a pair bound to this installation and store the refresh hash.

        The claims carry the fingerprint and the token version, which is what
        makes a copied token refusable on first use.
        """
        ttl = timedelta(hours=DEVICE_ACCESS_TOKEN_HOURS)
        access_token, _ = create_access_token(
            subject=installation.id,
            token_type=TOKEN_TYPE_DEVICE,
            expires_in=ttl,
            claims={
                "num": str(installation.number_id),
                "agent": str(installation.agent_id),
                "fp": installation.device_fingerprint_hash,
                "tv": installation.token_version,
            },
        )
        raw_refresh = new_opaque_token()
        # Keep the one being replaced, so that presenting it later is
        # attributable rather than merely refusable (migration 005).
        installation.previous_refresh_token_hash = installation.refresh_token_hash
        installation.refresh_token_hash = sha256_hex(raw_refresh)
        await self.session.flush()
        return DeviceTokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=int(ttl.total_seconds()),
        )

    async def refresh_device(
        self, raw_token: str
    ) -> tuple[InstallationModel, DeviceTokenPair]:
        """Rotate an installation's pair.

        **On reuse this refuses and can do no more, and that is a real limit.**
        A spent refresh token matches no row, so there is no installation whose
        ``token_version`` we could increment — the caller is refused with
        ``refresh_reused`` and any pair the thief already obtained keeps
        working until it expires. Detecting reuse properly needs the previous
        hash kept alongside the current one; it is not kept today.

        This docstring said the opposite until 2026-09-06 — that reuse "kills
        every token already issued" — which described a control that was never
        implemented. Recorded in ``docs/ASSUMPTIONS.md``; a comment claiming a
        mitigation is worse than none, because it stops the next reader looking.

        A replay is deliberately *not* a reason to stop accepting the phone's
        queued calls (SPEC §4.3): the installation stays ``active``.
        """
        installation = await self.session.scalar(
            select(InstallationModel).where(
                InstallationModel.refresh_token_hash == sha256_hex(raw_token)
            )
        )
        if installation is None:
            replayed = await self.session.scalar(
                select(InstallationModel).where(
                    InstallationModel.previous_refresh_token_hash
                    == sha256_hex(raw_token)
                )
            )
            if replayed is not None:
                await self._handle_refresh_reuse(replayed)
            # Either the token we just acted on, or one that was never ours.
            raise UnauthorizedError(ErrorCode.REFRESH_REUSED)
        if installation.status in (
            InstallationStatus.REVOKED,
            InstallationStatus.REVOKED_PENDING_CONFIRMATION,
        ):
            raise UnauthorizedError(ErrorCode.INSTALLATION_REVOKED)

        # N34, and the order is the rule. The refusal happens **here and only
        # here**, and only once the phone has told us its queue is empty. An
        # under-version client uploads its backlog with 200s first; refusing
        # before that would destroy the records it is holding, which is the
        # one thing the gate must never do (SPEC §4.3, test
        # test_old_client_drains_then_refused).
        block = await self.update_block(installation)
        if block.required and await self.queue_is_drained(installation):
            log.info(
                "version_gate_refused",
                installation_id=str(installation.id),
                min_version_code=block.min_version_code,
            )
            raise VersionUnsupportedError(detail={"update": block.model_dump()})

        pair = await self.issue_device_pair(installation)
        await self.session.commit()
        return installation, pair

    async def _handle_refresh_reuse(self, installation: InstallationModel) -> None:
        """A spent refresh token was presented. Kill both pairs and say so.

        **We know a replay happened and we do not know who did it.** The token
        was used twice; one of those was the employee's handset and one was
        not, and nothing in the request distinguishes them — the thief and the
        phone send the same bytes. So both are disconnected, which is the only
        action that is correct whichever party is which, and the alert says
        that rather than implying the handset is compromised.

        The installation stays **active** (SPEC §4.3). Refusing its queued
        calls would destroy records over a credential problem, and re-enrolling
        on the same number keeps that queue: the duplicate-call check is keyed
        on ``number_id``, which does not change, so the phone can upload
        everything it was holding once it has a new code.
        """
        installation.token_version += 1
        installation.refresh_token_hash = None
        installation.previous_refresh_token_hash = None
        await AlertService(self.session).raise_alert(
            kind=AlertKind.CREDENTIAL_REPLAY,
            severity=AlertSeverity.CRITICAL,
            scope=installation.id,
            installation_id=installation.id,
            agent_id=installation.agent_id,
            detail={
                "reason": "refresh_token_reused",
                # Named because it is the thing an admin will want to assume
                # away: we cannot tell which use was the real handset.
                "attributable_to_device": False,
                "queued_records_preserved": True,
            },
        )
        await self.audit.record(
            action=AuditAction.INSTALLATION_REVOKED,
            object_type="installations",
            object_id=installation.id,
            actor_type=ActorType.SYSTEM,
            detail={"reason": "refresh_token_reused"},
        )
        await self.session.commit()
        log.warning(
            "refresh_token_reused",
            installation_id=str(installation.id),
            agent_id=str(installation.agent_id),
        )

    async def principal_for_claims(
        self,
        claims: dict,
        installation_header: str | None,
        fingerprint_header: str | None,
    ) -> Principal:
        """Build a device principal, checking the token against its headers.

        This is what N24's "a token copied to another device is rejected on
        first use" means concretely. The honest limit is written down in SPEC
        §4.2: fingerprint binding raises the cost of credential theft, it does
        not defeat an attacker with root on the handset.
        """
        installation_id = uuid.UUID(claims["sub"])
        if installation_header and installation_header != str(installation_id):
            raise UnauthorizedError(ErrorCode.INSTALLATION_MISMATCH)
        if fingerprint_header and fingerprint_header != claims.get("fp"):
            raise UnauthorizedError(ErrorCode.INSTALLATION_MISMATCH)

        installation = await self.session.get(InstallationModel, installation_id)
        if installation is None:
            raise UnauthorizedError()
        if installation.status in (
            InstallationStatus.REVOKED,
            InstallationStatus.REVOKED_PENDING_CONFIRMATION,
        ):
            raise UnauthorizedError(ErrorCode.INSTALLATION_REVOKED)
        if claims.get("tv") != installation.token_version:
            # token_version moved — a revoke or a replay — so every token
            # minted before that moment is dead.
            raise UnauthorizedError(ErrorCode.INSTALLATION_MISMATCH)

        return Principal(
            kind="device",
            id=installation.id,
            role="device",
            permissions=frozenset(),
            agent_id=installation.agent_id,
            installation_id=installation.id,
            display_name=str(installation.id),
        )

    async def activate(
        self, installation: InstallationModel, method: VerificationMethod
    ) -> InstallationModel:
        """Verification succeeded: bind the number to this phone.

        If another installation already holds the number it becomes
        ``replaced`` and an alert is raised, because an unexpected rebinding is
        exactly what a stolen credential looks like.
        """
        previous = await self.session.scalar(
            select(InstallationModel).where(
                InstallationModel.number_id == installation.number_id,
                InstallationModel.status == InstallationStatus.ACTIVE,
                InstallationModel.id != installation.id,
            )
        )
        if previous is not None:
            previous.status = InstallationStatus.REPLACED
            # Its open alerts go with it: nobody will fix a handset the agent
            # no longer holds, so nobody acknowledges them, and they sit at the
            # top of a page sorted worst-first for ever.
            await AlertService(self.session).resolve_all_for(previous.id)
            previous.replaced_at = clock.now()
            previous.funnel_stage = FunnelStage.REVOKED
            previous.funnel_changed_at = clock.now()
            # Flush before the new row claims the number: the partial unique
            # index would otherwise see two active rows for one instant.
            await self.session.flush()
            await self.alerts.raise_alert(
                kind=AlertKind.INSTALLATION_REBOUND,
                severity=AlertSeverity.WARNING,
                scope=installation.number_id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                number_id=installation.number_id,
                detail={"previous_installation_id": str(previous.id)},
            )
            await self.audit.record(
                action=AuditAction.INSTALLATION_REBOUND,
                object_type="installations",
                object_id=installation.id,
                actor_type=ActorType.DEVICE,
                detail={"previous_installation_id": str(previous.id)},
            )

        installation.status = InstallationStatus.ACTIVE
        installation.verification_method = method
        installation.verified_at = clock.now()
        installation.funnel_stage = (
            FunnelStage.VERIFIED_BY_ADMIN
            if method is VerificationMethod.ADMIN_ATTESTED
            else FunnelStage.NUMBER_VERIFIED
        )
        installation.funnel_changed_at = clock.now()
        await self.session.flush()
        log.info(
            "installation_activated",
            installation_id=str(installation.id),
            method=method.value,
        )
        return installation

    async def attest(
        self,
        installation_id: uuid.UUID,
        reason: str,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> InstallationModel:
        """Admin-attested verification (T142, SPEC §9.3).

        Rendered differently from ``number_verified`` everywhere it appears,
        because attested is weaker evidence than proven and the identity anchor
        must never silently degrade.
        """
        installation = await self.get(installation_id)
        if installation.status in (
            InstallationStatus.REVOKED,
            InstallationStatus.REVOKED_PENDING_CONFIRMATION,
        ):
            raise ConflictError(ErrorCode.INSTALLATION_REVOKED)

        installation.attested_by = actor_id
        installation.attest_reason = reason
        await self.activate(installation, VerificationMethod.ADMIN_ATTESTED)
        await self.audit.record(
            action=AuditAction.INSTALLATION_ATTESTED,
            object_type="installations",
            object_id=installation.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"reason": reason},
        )
        await self.session.commit()
        return installation

    async def revoke(
        self,
        installation_id: uuid.UUID,
        actor_id: uuid.UUID,
        ip: str | None,
        reason: str | None = None,
    ) -> InstallationModel:
        """Stop capture and kill every issued token (UC-08).

        ``token_version`` is incremented, so tokens already on the phone are
        dead immediately. The status is ``revoked_pending_confirmation`` until
        the handset comes back and confirms its local audio is gone — Bonvi
        does not own the device, and a product that implied a completed wipe
        would be lying.
        """
        installation = await self.get(installation_id)
        pending_records, pending_bytes = await DeviceService(
            self.session
        ).queue_snapshot(installation_id)

        await AlertService(self.session).resolve_all_for(installation_id)
        installation.status = InstallationStatus.REVOKED_PENDING_CONFIRMATION
        installation.revoked_at = clock.now()
        installation.token_version += 1
        installation.refresh_token_hash = None
        installation.revoke_pending_records = pending_records
        installation.revoke_pending_bytes = pending_bytes
        installation.funnel_stage = FunnelStage.REVOKED
        installation.funnel_changed_at = clock.now()

        await self.audit.record(
            action=AuditAction.INSTALLATION_REVOKED,
            object_type="installations",
            object_id=installation.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={
                "reason": reason,
                "pending_records": installation.revoke_pending_records,
                "pending_bytes": installation.revoke_pending_bytes,
            },
        )
        await self.session.commit()
        log.info("installation_revoked", installation_id=str(installation.id))
        return installation

    async def confirm_revocation(self, installation: InstallationModel) -> None:
        """The phone reported that its local audio is gone (UC-08)."""
        installation.status = InstallationStatus.REVOKED
        installation.revoke_confirmed_at = clock.now()
        await self.session.commit()


@dataclass(frozen=True)
class StrandedInstallation:
    """One phone that a proposed minimum version would refuse.

    A plain dataclass, like :class:`DeviceTokenPair` above: the service stays
    free of the wire layer, and the router turns it into a response schema.
    """

    installation_id: uuid.UUID
    agent_name: str
    device: str
    app_version: str | None
    app_version_code: int | None
    status: InstallationStatus
    last_heartbeat_at: datetime | None


class VersionGateService:
    """Who the version gate would strand, and the decision to strand them.

    Lives beside ``installations`` and not beside the APK catalogue on purpose.
    The minimum supported version is a statement about *the fleet* — which
    phones may keep reporting — and only this module can see them. It also
    keeps the import graph acyclic: ``installations`` already reaches both
    ``catalog`` and ``settings``, and the reverse edge would be a cycle.

    **Raising the minimum is not a configuration change.** These are personally
    owned handsets; a phone below the new floor drains its queue and is then
    refused, and it stays refused until somebody physically reaches that
    salesperson and updates the app. So the count comes first and the change
    has to name it (SPEC §4.3, N34, UC-28).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SettingsService(session)
        self.audit = AuditService(session)

    async def impact_of(
        self, version_code: int
    ) -> tuple[int, list[StrandedInstallation]]:
        """Installations that would be refused at ``version_code``.

        Counts a phone whose reported code is **unknown** as *not* stranded, to
        match the gate: ``_version_code`` fails open for a row with no reported
        code, so counting it here would overstate the cost of a change and
        report a phone as stranded that the gate will let through.
        """
        # One statement with the joins, not a row loop: the whole point of the
        # page is to show *which* phones, and fetching the agent and the model
        # per installation is the N+1 that makes an admin's confirmation screen
        # slow exactly when the fleet is large enough for the decision to matter.
        statement = (
            select(
                InstallationModel.id,
                InstallationModel.app_version,
                InstallationModel.app_version_code,
                InstallationModel.status,
                AgentModel.full_name,
                DeviceModel.manufacturer,
                DeviceModel.model,
                DeviceHealthModel.last_heartbeat_at,
            )
            .select_from(InstallationModel)
            .join(AgentModel, AgentModel.id == InstallationModel.agent_id)
            .join(DeviceModel, DeviceModel.id == InstallationModel.device_id)
            .outerjoin(
                DeviceHealthModel,
                DeviceHealthModel.installation_id == InstallationModel.id,
            )
            .where(
                InstallationModel.status.in_(
                    (InstallationStatus.ACTIVE, InstallationStatus.REPLACED)
                ),
                InstallationModel.app_version_code.is_not(None),
                InstallationModel.app_version_code < version_code,
            )
            .order_by(InstallationModel.app_version_code, InstallationModel.id)
        )
        rows = [
            StrandedInstallation(
                installation_id=row.id,
                agent_name=row.full_name,
                device=f"{row.manufacturer} {row.model}".strip(),
                app_version=row.app_version,
                app_version_code=row.app_version_code,
                status=row.status,
                last_heartbeat_at=row.last_heartbeat_at,
            )
            for row in (await self.session.execute(statement)).all()
        ]
        return len(rows), rows

    async def unknown_version_count(self) -> int:
        """Active phones whose version we have never been told.

        Shown next to the impact because it is the honest uncertainty in it: the
        gate lets these through today, and each one is a phone that might be
        below the new floor and we cannot say.
        """
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(InstallationModel)
                .where(
                    InstallationModel.status.in_(
                        (InstallationStatus.ACTIVE, InstallationStatus.REPLACED)
                    ),
                    InstallationModel.app_version_code.is_(None),
                )
            )
            or 0
        )

    async def set_minimum(
        self,
        version_code: int,
        acknowledged_stranded: int,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> int:
        """Raise or lower the floor, having said how many phones it costs.

        ``acknowledged_stranded`` must equal the count *right now*. It is not
        ceremony: it fails when the number changed between looking and
        deciding, which is exactly when the admin's mental model is stale — a
        phone enrolled in the last minute, or one that finally reported an old
        version. Lowering the floor strands nobody, so a zero cost is trivially
        acknowledged and the check costs nothing.
        """
        stranded, _ = await self.impact_of(version_code)
        if acknowledged_stranded != stranded:
            raise ConflictError(
                ErrorCode.STRANDED_COUNT_MISMATCH,
                detail={
                    "stranded_now": stranded,
                    "acknowledged": acknowledged_stranded,
                    "hint": "re-read the impact and confirm the current number",
                },
            )
        await self.settings.update(
            SETTING_MIN_VERSION_CODE,
            version_code,
            confirm=True,
            actor_id=actor_id,
            ip=ip,
        )
        log.info(
            "min_version_raised", version_code=version_code, stranded=stranded
        )
        return stranded
