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
from datetime import timedelta

from sqlalchemy import select
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


def _version_code(app_version: str | None, current) -> int:
    """Best-effort integer for a reported version string.

    The app sends ``X-App-Version-Code`` on every request and stores the code
    on enrolment; this is the fallback for a row written before that, and it
    fails **open** — an unparseable version is treated as current, because
    refusing a client we cannot identify is the one outcome N34 forbids.
    """
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
        installed = _version_code(installation.app_version, current)
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

        Reuse increments ``token_version``, killing every token already issued,
        and leaves the installation ``active``: a replayed credential is not a
        reason to stop accepting the phone's queued calls (SPEC §4.3).
        """
        installation = await self.session.scalar(
            select(InstallationModel).where(
                InstallationModel.refresh_token_hash == sha256_hex(raw_token)
            )
        )
        if installation is None:
            # Either a token from a previous rotation or one that was never
            # ours. We cannot tell which, and only one of those is safe.
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
