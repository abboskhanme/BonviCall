"""Device enrolment and verification (SPEC §4.2, §9).

``/enrolment/redeem`` is public — the code is the only secret it carries, and
it is single-use and expires in 24 hours. Everything after it needs the
provisional token, which is **scoped**: an unverified phone cannot upload a
single call, because ``POST /calls`` sits behind
``require_active_installation``. The privacy boundary starts here, not at the
first call.

Every handler is one service call. The orchestration and the transaction belong
to ``EnrolmentService``; a router that commits has started making business
decisions (CONVENTIONS.md §2).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from src.api.device.deps import InstallationDep
from src.core import clock
from src.core.deps import SessionDep
from src.core.enums import VerificationState
from src.modules.enrolment.rules import display_number
from src.modules.enrolment.schemas import (
    DeviceCallbackStartOut,
    DeviceMsisdnVerifyIn,
    DeviceRedeemIn,
    DeviceRedeemOut,
    DeviceVerificationStatusOut,
    IssuedTokensOut,
    RedeemAgentOut,
    RedeemNumberOut,
    RedeemVerificationOut,
)
from src.modules.enrolment.service import EnrolmentService

router = APIRouter(prefix="/enrolment", tags=["Device enrolment"])

#: The provisional token's life. Long enough to walk screens E2–E6, short
#: enough that an abandoned enrolment does not leave a usable credential.
PROVISIONAL_TOKEN_SECONDS = 900


@router.post(
    "/redeem", response_model=DeviceRedeemOut, status_code=status.HTTP_201_CREATED
)
async def redeem(
    payload: DeviceRedeemIn, request: Request, session: SessionDep
) -> DeviceRedeemOut:
    """Public, rate-limited. Turns a code into a ``pending`` installation."""
    result = await EnrolmentService(session).redeem(
        payload, request.client.host if request.client else None
    )
    return DeviceRedeemOut(
        installation_id=result.installation.id,
        status=result.installation.status,
        provisional_token=result.tokens.access_token,
        expires_in=PROVISIONAL_TOKEN_SECONDS,
        agent=RedeemAgentOut(id=result.agent_id, full_name=result.agent_name),
        number=RedeemNumberOut(
            e164=result.number.e164, display=display_number(result.number.e164)
        ),
        verification=RedeemVerificationOut(
            required=True,
            callback_msisdn=result.callback_msisdn,
            receiver_status=result.receiver_status,
            window_seconds=result.window_seconds,
        ),
        server_time=clock.now(),
    )


@router.post("/verify/msisdn", response_model=DeviceVerificationStatusOut)
async def verify_msisdn(
    payload: DeviceMsisdnVerifyIn,
    installation: InstallationDep,
    session: SessionDep,
) -> DeviceVerificationStatusOut:
    """Route 1: the SIM's own MSISDN (SPEC §9.1).

    A null, empty or short ``line1_number`` is **never** a match — it is
    ``msisdn_empty`` and the app moves to route 2. Treating "I don't know" as
    "yes" would attribute a phone to a number it does not hold.

    **Replaying this mints a fresh token pair, and that is deliberate.** It is
    what rescues a handset whose verification succeeded and whose response was
    lost — the field case, on a tunnel that drops every few hours: the server
    activated the installation, the phone has nothing to show for it, and
    without re-minting the agent would have to start enrolment again.

    The cost is that the provisional access token stays usable for the rest of
    its ≤30 minutes and could mint a pair outside the version gate, which is
    otherwise the sole business of ``POST /auth/refresh`` (N34). It is accepted
    because a client that enrolled minutes ago is running a freshly installed
    APK and so cannot be the under-version client the gate exists to stop,
    while a lost response is ordinary. Reviewed 2026-09-06; recorded here so it
    reads as a decision and not as an oversight somebody should close.
    """
    tokens = await EnrolmentService(session).complete_msisdn_verification(
        installation, payload.line1_number, payload.subscription_id, payload.sim_slot
    )
    return DeviceVerificationStatusOut(
        state=VerificationState.MATCHED,
        status=installation.status,
        tokens=IssuedTokensOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
    )


@router.post("/verify/callback/start", response_model=DeviceCallbackStartOut)
async def start_callback(
    installation: InstallationDep, session: SessionDep
) -> DeviceCallbackStartOut:
    """Route 2 — the load-bearing one, since SMS is out of scope.

    409 ``callback_receiver_down`` when no receiver has checked in recently:
    raising a challenge the agent cannot possibly satisfy is worse than saying
    so, and the Uzbek message tells them to contact the admin.
    """
    verification, receiver = await EnrolmentService(session).start_callback(installation)
    return DeviceCallbackStartOut(
        verification_id=verification.id,
        callback_msisdn=receiver.msisdn,
        expires_at=verification.expires_at,
    )


@router.get("/verify/callback/status", response_model=DeviceVerificationStatusOut)
async def callback_status(
    verification_id: uuid.UUID,
    installation: InstallationDep,
    session: SessionDep,
) -> DeviceVerificationStatusOut:
    """Polled every two seconds for at most five minutes."""
    verification, tokens = await EnrolmentService(
        session
    ).complete_callback_verification(verification_id, installation)
    if tokens is None:
        return DeviceVerificationStatusOut(
            state=verification.state, failure=verification.failure_outcome
        )
    return DeviceVerificationStatusOut(
        state=verification.state,
        status=installation.status,
        tokens=IssuedTokensOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
    )
