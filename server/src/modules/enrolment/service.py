"""Enrolment: codes, redemption, number verification (T32, T34, SPEC §9).

**Route 2 (the callback) is load-bearing, not a fallback.** SMS was removed
from scope, and route 1 — the SIM reporting its own MSISDN — is empty on most
Uzbek SIMs. If the callback receiver is down, nobody in the fleet can enrol, so
screen E5 is told to refuse rather than letting an agent dial into nothing.

Every failure writes an ``enrolment_attempts`` row. A stalled enrolment must be
an **event**, not silence: a rollout that has quietly stopped looks exactly like
one that is working until go-live.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import (
    ActorType,
    AuditAction,
    EnrolmentAttemptKind,
    EnrolmentOutcome,
    InstallationStatus,
    ReceiverStatus,
    VerificationMethod,
    VerificationState,
)
from src.core.errors import ConflictError, ErrorCode, GoneError, NotFoundError
from src.core.logging import get_logger
from src.core.phone import phone_key
from src.core.security import sha256_hex
from src.modules.agents.models import AgentModel
from src.modules.audit.service import AuditService
from src.modules.catalog.service import CatalogService
from src.modules.devices.service import DeviceReport, DeviceService
from src.modules.enrolment.models import (
    CallbackEventModel,
    CallbackReceiverModel,
    EnrolmentAttemptModel,
    EnrolmentCodeModel,
    NumberVerificationModel,
)
from src.modules.enrolment.rules import (
    CODE_ALPHABET,
    CODE_LENGTH,
    msisdn_matches,
    normalise_code,
)
from src.modules.enrolment.schemas import DeviceRedeemIn, ReceiverStatusResponse
from src.modules.installations.models import InstallationModel
from src.modules.installations.service import DeviceTokenPair, InstallationService
from src.modules.numbers.models import RegisteredNumberModel
from src.modules.numbers.service import NumberService
from src.modules.settings.service import SettingsService

log = get_logger(__name__)

SETTING_CODE_TTL_HOURS = "enrolment.code_ttl_hours"
SETTING_CALLBACK_WINDOW_SECONDS = "enrolment.callback_window_seconds"

#: SPEC §4.0: five attempts against one code auto-revoke it and raise an alert.
MAX_CODE_ATTEMPTS = 5

#: A receiver silent for this long is not usable for a new challenge (§9.4).
RECEIVER_DEGRADED_SECONDS = 180
RECEIVER_DOWN_SECONDS = 300


@dataclass(frozen=True)
class Redemption:
    """Everything screen E1 needs after a code is accepted.

    Assembled in one service call so the router does no orchestration and owns
    no transaction — a router that commits is a router that has started making
    business decisions (CONVENTIONS.md §2).
    """

    installation: InstallationModel
    number: RegisteredNumberModel
    agent_name: str
    agent_id: uuid.UUID
    tokens: DeviceTokenPair
    callback_msisdn: str | None
    receiver_status: ReceiverStatus | None
    window_seconds: int


class EnrolmentService:
    """Issue and redeem codes; run the two verification routes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.devices = DeviceService(session)
        self.installations = InstallationService(session)
        self.numbers = NumberService(session)

    # --- Codes (panel) ----------------------------------------------------

    async def issue_code(
        self, number_id: uuid.UUID, actor_id: uuid.UUID, ip: str | None
    ) -> EnrolmentCodeModel:
        """Mint a single-use code for a registered number.

        The agent is **frozen at issue**, taken from the assignment in force
        now, so the install landing page can greet the right person even if the
        line changes hands before the code is redeemed.
        """
        number = await self.session.get(RegisteredNumberModel, number_id)
        if number is None:
            raise NotFoundError()
        assignment = await self.numbers.holder_at(number_id, clock.now())
        if assignment is None:
            raise ConflictError(
                ErrorCode.CONFLICT,
                detail={"reason": "number is not assigned to an agent"},
            )

        ttl_hours = await self._setting_int(SETTING_CODE_TTL_HOURS)
        code = EnrolmentCodeModel(
            code=await self._unique_code(),
            number_id=number_id,
            agent_id=assignment.agent_id,
            issued_by=actor_id,
            expires_at=clock.now() + timedelta(hours=ttl_hours),
        )
        self.session.add(code)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.ENROLMENT_CODE_ISSUED,
            object_type="enrolment_codes",
            object_id=code.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"number_id": str(number_id), "agent_id": str(assignment.agent_id)},
        )
        await self.session.commit()
        return code

    async def list_codes(
        self, number_id: uuid.UUID | None = None, active_only: bool = False
    ) -> tuple[list[EnrolmentCodeModel], int]:
        statement = select(EnrolmentCodeModel).order_by(
            EnrolmentCodeModel.created_at.desc()
        )
        if number_id is not None:
            statement = statement.where(EnrolmentCodeModel.number_id == number_id)
        if active_only:
            statement = statement.where(
                EnrolmentCodeModel.redeemed_at.is_(None),
                EnrolmentCodeModel.revoked_at.is_(None),
            )
        rows = list((await self.session.scalars(statement)).all())
        return rows, len(rows)

    async def revoke_code(
        self, code_id: uuid.UUID, actor_id: uuid.UUID | None, ip: str | None
    ) -> EnrolmentCodeModel:
        code = await self.session.get(EnrolmentCodeModel, code_id)
        if code is None:
            raise NotFoundError()
        if code.revoked_at is None:
            code.revoked_at = clock.now()
            code.revoked_by = actor_id
        await self.audit.record(
            action=AuditAction.ENROLMENT_CODE_REVOKED,
            object_type="enrolment_codes",
            object_id=code.id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            actor_user_id=actor_id,
            ip=ip,
        )
        await self.session.commit()
        return code

    async def list_attempts(
        self,
        number_id: uuid.UUID | None = None,
        installation_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> tuple[list[EnrolmentAttemptModel], int]:
        statement = (
            select(EnrolmentAttemptModel)
            .order_by(EnrolmentAttemptModel.created_at.desc())
            .limit(limit)
        )
        if number_id is not None:
            statement = statement.where(EnrolmentAttemptModel.number_id == number_id)
        if installation_id is not None:
            statement = statement.where(
                EnrolmentAttemptModel.installation_id == installation_id
            )
        rows = list((await self.session.scalars(statement)).all())
        return rows, len(rows)

    # --- Redemption (device) ---------------------------------------------

    async def redeem(self, payload: DeviceRedeemIn, ip: str | None) -> Redemption:
        """Turn a code into a ``pending`` installation.

        Every failure path here is a distinct code with its own Uzbek sentence
        and its own next action, and every one of them lands in
        ``enrolment_attempts`` so it appears in the admin's list with a
        timestamp (UC-01's acceptance criterion).
        """
        normalised = normalise_code(payload.code)
        code = await self.session.scalar(
            select(EnrolmentCodeModel).where(EnrolmentCodeModel.code == normalised)
        )
        if code is None:
            await self._attempt(
                EnrolmentAttemptKind.CODE_REDEEM,
                EnrolmentOutcome.CODE_NOT_FOUND,
                payload=payload,
                ip=ip,
            )
            await self.session.commit()
            raise NotFoundError(ErrorCode.ENROLMENT_CODE_NOT_FOUND)

        code.attempt_count += 1
        if code.attempt_count >= MAX_CODE_ATTEMPTS and code.redeemed_at is None:
            # Brute force against an eight-character code is slow, but the code
            # is also read aloud in an office; auto-revoking is cheap.
            code.revoked_at = code.revoked_at or clock.now()

        if code.revoked_at is not None:
            await self._fail_redeem(code, EnrolmentOutcome.CODE_REVOKED, payload, ip)
            raise ConflictError(ErrorCode.ENROLMENT_CODE_REVOKED)
        if code.redeemed_at is not None:
            holder = await self.installations.get_optional(
                code.redeemed_by_installation_id
            )
            device_model = await self.devices.describe(
                holder.device_id if holder else None
            )
            await self._fail_redeem(code, EnrolmentOutcome.CODE_ALREADY_USED, payload, ip)
            raise ConflictError(
                ErrorCode.ENROLMENT_CODE_USED,
                detail={
                    "redeemed_at": code.redeemed_at.isoformat(),
                    "device_model": device_model,
                },
            )
        if code.expires_at <= clock.now():
            await self._fail_redeem(code, EnrolmentOutcome.CODE_EXPIRED, payload, ip)
            raise GoneError(
                ErrorCode.ENROLMENT_CODE_EXPIRED,
                detail={"expired_at": code.expires_at.isoformat()},
            )

        number = await self.session.get(RegisteredNumberModel, code.number_id)
        device_id = await self.devices.upsert_from_report(
            DeviceReport(**payload.device.model_dump())
        )
        installation = await self.installations.create_pending(
            number_id=code.number_id,
            agent_id=code.agent_id,
            device_id=device_id,
            device_fingerprint_hash=payload.device_fingerprint,
            app_version=payload.app.version,
            # The number the gate compares. It arrives on every enrolment and
            # was previously discarded, leaving the gate to reconstruct one
            # from the version *string* (see migration 003).
            app_version_code=payload.app.version_code,
            app_variant=payload.app.variant,
            sim_subscription_id=payload.sim_subscription_id,
            sim_slot=payload.sim_slot,
        )

        code.redeemed_at = clock.now()
        code.redeemed_by_installation_id = installation.id
        await self._attempt(
            EnrolmentAttemptKind.CODE_REDEEM,
            EnrolmentOutcome.OK,
            payload=payload,
            ip=ip,
            code=code,
            installation_id=installation.id,
        )
        tokens = await self.installations.issue_device_pair(installation)
        receiver = await self.usable_receiver()
        window = await self._setting_int(SETTING_CALLBACK_WINDOW_SECONDS)
        agent = await self.session.get(AgentModel, code.agent_id)
        await self.session.commit()
        log.info(
            "enrolment_redeemed",
            installation_id=str(installation.id),
            number_id=str(code.number_id),
        )
        return Redemption(
            installation=installation,
            number=number,
            agent_name=agent.full_name,
            agent_id=agent.id,
            tokens=tokens,
            callback_msisdn=receiver.msisdn if receiver else None,
            receiver_status=receiver.status if receiver else None,
            window_seconds=window,
        )

    async def invitation_for(
        self, raw_code: str
    ) -> tuple[str, str, str, int | None] | None:
        """What the install page needs, or ``None`` for any unusable code.

        Named ``invitation_for`` and not ``landing_context`` because the §2
        grep for SQL in a router is ``grep "text("``, and "context(" matches
        it. A check that cries wolf is a check people learn to skip.

        One answer for unknown, used, revoked and expired: the page must not
        tell an unauthenticated caller which, and the agent's next action is
        the same in all four cases.
        """
        code = await self.session.scalar(
            select(EnrolmentCodeModel).where(
                EnrolmentCodeModel.code == normalise_code(raw_code)
            )
        )
        if code is None or code.revoked_at is not None:
            return None
        if code.redeemed_at is not None or code.expires_at <= clock.now():
            return None
        agent = await self.session.get(AgentModel, code.agent_id)
        number = await self.session.get(RegisteredNumberModel, code.number_id)
        version_code = await CatalogService(self.session).current_version_code()
        return agent.full_name, number.e164, code.code, version_code

    # --- Verification route 1: the SIM's own MSISDN -----------------------

    async def verify_msisdn(
        self, installation: InstallationModel, line1_number: str | None
    ) -> bool:
        """True when the SIM reported a number matching the registered one.

        ``getLine1Number()`` returning null is **never** a match (UC-04,
        non-negotiable). It moves the flow to route 2 rather than failing the
        enrolment, because on most Uzbek SIMs empty is the normal answer.
        """
        number = await self.session.get(RegisteredNumberModel, installation.number_id)
        matched = msisdn_matches(line1_number, number.phone_key)
        outcome = (
            EnrolmentOutcome.OK
            if matched
            else (
                EnrolmentOutcome.MSISDN_EMPTY
                if not (line1_number or "").strip()
                else EnrolmentOutcome.NUMBER_MISMATCH
            )
        )
        self.session.add(
            EnrolmentAttemptModel(
                kind=EnrolmentAttemptKind.MSISDN_CHECK,
                outcome=outcome,
                number_id=installation.number_id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                step="E5",
            )
        )
        await self.session.flush()
        return matched

    async def complete_msisdn_verification(
        self,
        installation: InstallationModel,
        line1_number: str | None,
        subscription_id: int | None,
        sim_slot: int | None,
    ) -> DeviceTokenPair:
        """Route 1 end to end: match, activate, issue. Raises when it does not.

        The refusal distinguishes "the SIM told us nothing" from "the SIM told
        us a different number", because the app's next screen differs: the
        first moves to the callback, the second says which SIM to pick.
        """
        matched = await self.verify_msisdn(installation, line1_number)
        if not matched:
            await self.session.commit()
            raise ConflictError(
                ErrorCode.MSISDN_UNAVAILABLE
                if not (line1_number or "").strip()
                else ErrorCode.NUMBER_MISMATCH
            )
        if subscription_id is not None:
            installation.sim_subscription_id = subscription_id
            installation.sim_slot = sim_slot
        await self.installations.activate(installation, VerificationMethod.SIM_MSISDN)
        tokens = await self.installations.issue_device_pair(installation)
        await self.session.commit()
        return tokens

    async def complete_callback_verification(
        self, verification_id: uuid.UUID, installation: InstallationModel
    ) -> tuple[NumberVerificationModel, DeviceTokenPair | None]:
        """Poll route 2. Returns tokens only once the challenge has matched."""
        verification = await self.verification_status(verification_id, installation)
        if verification.state is not VerificationState.MATCHED:
            return verification, None
        if installation.status is not InstallationStatus.ACTIVE:
            await self.installations.activate(installation, VerificationMethod.CALLBACK)
        tokens = await self.installations.issue_device_pair(installation)
        await self.session.commit()
        return verification, tokens

    async def reissue_tokens(self, installation: InstallationModel) -> DeviceTokenPair:
        """A fresh pair for a phone that still holds a valid access token."""
        tokens = await self.installations.issue_device_pair(installation)
        await self.session.commit()
        return tokens

    async def report_callback_event(
        self,
        receiver: CallbackReceiverModel,
        caller_e164: str | None,
        cli_presented: bool,
        receiver_epoch_ms: int | None,
        heartbeat: bool,
    ) -> tuple[bool, bool, ReceiverStatus]:
        """One receiver report: heartbeat, event, or both (§9.4).

        Returns ``(stored, matched, status)``. Owns the transaction, so the
        router stays a router.
        """
        status = await self.touch_receiver(receiver)
        if heartbeat:
            await self.session.commit()
            return False, False, status
        _, verification = await self.record_callback_event(
            receiver=receiver,
            caller_e164=caller_e164,
            cli_presented=cli_presented,
            receiver_epoch_ms=receiver_epoch_ms,
        )
        await self.session.commit()
        return True, verification is not None, status

    # --- Verification route 2: the callback -------------------------------

    async def start_callback(
        self, installation: InstallationModel
    ) -> tuple[NumberVerificationModel, CallbackReceiverModel]:
        """Open a five-minute challenge, or refuse if no receiver is up.

        Refusing is the point: raising a challenge the agent cannot possibly
        satisfy is worse than saying so (SPEC §9.2).
        """
        receiver = await self.usable_receiver()
        if receiver is None:
            self.session.add(
                EnrolmentAttemptModel(
                    kind=EnrolmentAttemptKind.CALLBACK_START,
                    outcome=EnrolmentOutcome.RECEIVER_DOWN,
                    number_id=installation.number_id,
                    installation_id=installation.id,
                    agent_id=installation.agent_id,
                    step="E5",
                )
            )
            await self.session.commit()
            raise ConflictError(ErrorCode.CALLBACK_RECEIVER_DOWN)

        window = await self._setting_int(SETTING_CALLBACK_WINDOW_SECONDS)
        verification = NumberVerificationModel(
            installation_id=installation.id,
            number_id=installation.number_id,
            method=VerificationMethod.CALLBACK,
            state=VerificationState.PENDING,
            expires_at=clock.now() + timedelta(seconds=window),
        )
        self.session.add(verification)
        self.session.add(
            EnrolmentAttemptModel(
                kind=EnrolmentAttemptKind.CALLBACK_START,
                outcome=EnrolmentOutcome.OK,
                number_id=installation.number_id,
                installation_id=installation.id,
                agent_id=installation.agent_id,
                step="E5",
            )
        )
        await self.session.commit()
        return verification, receiver

    async def verification_status(
        self, verification_id: uuid.UUID, installation: InstallationModel
    ) -> NumberVerificationModel:
        verification = await self.session.get(NumberVerificationModel, verification_id)
        if verification is None or verification.installation_id != installation.id:
            raise NotFoundError()
        if (
            verification.state is VerificationState.PENDING
            and verification.expires_at <= clock.now()
        ):
            verification.state = VerificationState.EXPIRED
            verification.failure_outcome = EnrolmentOutcome.TIMEOUT
            await self.session.commit()
        return verification

    async def record_callback_event(
        self,
        receiver: CallbackReceiverModel,
        caller_e164: str | None,
        cli_presented: bool,
        receiver_epoch_ms: int | None,
    ) -> tuple[CallbackEventModel, NumberVerificationModel | None]:
        """Store what the receiver saw and try to match it (SPEC §9.2 step 4).

        An event that matches nothing is stored with a reason and ignored —
        never dropped. If two pending verifications ever shared a caller key
        the matcher fails closed rather than guessing; a number has exactly one
        active assignment, so that state means something else is wrong.
        """
        event = CallbackEventModel(
            receiver_id=receiver.id,
            caller_e164=caller_e164,
            cli_presented=cli_presented,
            receiver_epoch_ms=receiver_epoch_ms,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)

        key = phone_key(caller_e164)
        if not cli_presented or key is None:
            event.unmatched_reason = "no_caller_id"
            await self._mark_no_caller_id(receiver)
            await self.session.commit()
            return event, None

        candidates = list(
            (
                await self.session.scalars(
                    select(NumberVerificationModel)
                    .join(
                        RegisteredNumberModel,
                        RegisteredNumberModel.id == NumberVerificationModel.number_id,
                    )
                    .where(
                        NumberVerificationModel.state == VerificationState.PENDING,
                        NumberVerificationModel.expires_at > clock.now(),
                        RegisteredNumberModel.phone_key == key,
                    )
                )
            ).all()
        )
        if len(candidates) != 1:
            event.unmatched_reason = "no_match" if not candidates else "ambiguous"
            await self.session.commit()
            return event, None

        verification = candidates[0]
        verification.state = VerificationState.MATCHED
        verification.matched_event_id = event.id
        event.matched_verification_id = verification.id
        self.session.add(
            EnrolmentAttemptModel(
                kind=EnrolmentAttemptKind.CALLBACK_MATCH,
                outcome=EnrolmentOutcome.OK,
                number_id=verification.number_id,
                installation_id=verification.installation_id,
                step="E5",
            )
        )
        await self.session.flush()
        return event, verification

    async def _mark_no_caller_id(self, receiver: CallbackReceiverModel) -> None:
        """R19 happening: the operator withheld the caller id.

        Recorded against the receiver rather than a verification, because at
        this point we do not know whose call it was — that is exactly the
        failure.
        """
        self.session.add(
            EnrolmentAttemptModel(
                kind=EnrolmentAttemptKind.CALLBACK_MATCH,
                outcome=EnrolmentOutcome.NO_CALLER_ID,
                step="E5",
                detail={"receiver_id": str(receiver.id)},
            )
        )

    # --- Receivers --------------------------------------------------------

    async def usable_receiver(self) -> CallbackReceiverModel | None:
        """An active receiver that has checked in recently enough to trust."""
        cutoff = clock.now() - timedelta(seconds=RECEIVER_DOWN_SECONDS)
        return await self.session.scalar(
            select(CallbackReceiverModel)
            .where(
                CallbackReceiverModel.is_active.is_(True),
                CallbackReceiverModel.last_heartbeat_at.is_not(None),
                CallbackReceiverModel.last_heartbeat_at > cutoff,
            )
            .order_by(CallbackReceiverModel.last_heartbeat_at.desc())
        )

    async def receiver_status(self) -> ReceiverStatusResponse:
        """Whether anybody can enrol right now, and through which receiver."""
        moment = clock.now()
        receivers = list(
            (
                await self.session.scalars(
                    select(CallbackReceiverModel).where(
                        CallbackReceiverModel.is_active.is_(True)
                    )
                )
            ).all()
        )
        usable = await self.usable_receiver()
        return ReceiverStatusResponse(
            enrolment_possible=usable is not None,
            receiver_name=usable.name if usable else None,
            receiver_msisdn=usable.msisdn if usable else None,
            status=(
                self.status_for(usable.last_heartbeat_at, moment)
                if usable
                else ReceiverStatus.DOWN
            ),
            active_receivers=len(receivers),
        )

    async def receiver_by_token(self, raw_token: str) -> CallbackReceiverModel | None:
        return await self.session.scalar(
            select(CallbackReceiverModel).where(
                CallbackReceiverModel.token_hash == sha256_hex(raw_token),
                CallbackReceiverModel.is_active.is_(True),
            )
        )

    async def touch_receiver(self, receiver: CallbackReceiverModel) -> ReceiverStatus:
        """Record a heartbeat and recompute the status (§9.4)."""
        receiver.last_heartbeat_at = clock.now()
        if receiver.status is not ReceiverStatus.UP:
            receiver.status = ReceiverStatus.UP
            receiver.status_changed_at = clock.now()
        await self.session.flush()
        return receiver.status

    @staticmethod
    def status_for(last_heartbeat_at: datetime | None, moment: datetime) -> ReceiverStatus:
        """3 minutes silent is degraded, 5 is down (§9.4). Pure, so the sweeper
        and the enrolment screen cannot disagree about it."""
        if last_heartbeat_at is None:
            return ReceiverStatus.DOWN
        silence = (moment - last_heartbeat_at).total_seconds()
        if silence >= RECEIVER_DOWN_SECONDS:
            return ReceiverStatus.DOWN
        if silence >= RECEIVER_DEGRADED_SECONDS:
            return ReceiverStatus.DEGRADED
        return ReceiverStatus.UP

    # --- Internals --------------------------------------------------------

    async def _unique_code(self) -> str:
        for _ in range(10):
            candidate = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            taken = await self.session.scalar(
                select(func.count())
                .select_from(EnrolmentCodeModel)
                .where(EnrolmentCodeModel.code == candidate)
            )
            if not taken:
                return candidate
        raise ConflictError(ErrorCode.CONFLICT, detail={"reason": "code space exhausted"})

    async def _fail_redeem(
        self,
        code: EnrolmentCodeModel,
        outcome: EnrolmentOutcome,
        payload: DeviceRedeemIn,
        ip: str | None,
    ) -> None:
        await self._attempt(
            EnrolmentAttemptKind.CODE_REDEEM, outcome, payload=payload, ip=ip, code=code
        )
        await self.session.commit()

    async def _attempt(
        self,
        kind: EnrolmentAttemptKind,
        outcome: EnrolmentOutcome,
        payload: DeviceRedeemIn,
        ip: str | None,
        code: EnrolmentCodeModel | None = None,
        installation_id: uuid.UUID | None = None,
    ) -> None:
        self.session.add(
            EnrolmentAttemptModel(
                kind=kind,
                outcome=outcome,
                code_id=code.id if code else None,
                number_id=code.number_id if code else None,
                agent_id=code.agent_id if code else None,
                installation_id=installation_id,
                step="E1",
                remote_ip=ip,
                app_version=payload.app.version,
                device_model=f"{payload.device.manufacturer} {payload.device.model}"[:64],
            )
        )
        await self.session.flush()

    async def _setting_int(self, key: str) -> int:
        return await SettingsService(self.session).get_int(key)
