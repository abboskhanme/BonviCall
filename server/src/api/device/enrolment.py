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
from src.core import clock, ratelimit
from src.core.deps import SessionDep
from src.core.enums import VerificationMethod, VerificationState
from src.core.errors import AppError
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
from src.modules.installations.service import DEVICE_ACCESS_TOKEN_HOURS

router = APIRouter(prefix="/enrolment", tags=["Device enrolment"])

#: The provisional token's life, **as the token is actually minted**.
#:
#: This was the literal 900, and it was wrong: :meth:`issue_device_pair` mints
#: every device access token — provisional ones included — for
#: ``DEVICE_ACCESS_TOKEN_HOURS``, so the app was told fifteen minutes and given
#: twelve hours. A client that believed the number would have discarded a
#: perfectly good credential and stranded itself on E5.
#:
#: Derived rather than restated, so the two cannot drift again. Twelve hours is
#: also what the wait-for-an-admin path needs: with
#: ``enrolment.allow_self_declared`` off and no callback receiver in service,
#: attestation is the only route left, and fifteen minutes is not a window in
#: which somebody gets to a panel.
#:
#: Past it, recovery costs nothing: a repeat redeem of the same code from the
#: same fingerprint on a still-pending installation is idempotent
#: (``EnrolmentService._resume_redeem``), so the app re-sends the code it
#: already holds rather than asking the agent to retype it.
PROVISIONAL_TOKEN_SECONDS = DEVICE_ACCESS_TOKEN_HOURS * 3600


@router.post(
    "/redeem", response_model=DeviceRedeemOut, status_code=status.HTTP_201_CREATED
)
async def redeem(
    payload: DeviceRedeemIn, request: Request, session: SessionDep
) -> DeviceRedeemOut:
    """Public, rate-limited. Turns a code into a ``pending`` installation.

    Ten **failed** redemptions an hour from one address (SPEC §4.0). Failures
    only, because the fleet enrols over one office Wi-Fi and so arrives as one
    address: counting successes would refuse the eleventh salesperson of the
    day, and counting the idempotent resume above would refuse the very handset
    whose response was lost. ``core/ratelimit.py`` states the rule.

    The other half of §4.0's limit — five attempts per code, then the code is
    revoked — is ``EnrolmentService.MAX_CODE_ATTEMPTS``, counted on the code row
    rather than in memory. This window is what stops somebody working through
    *different* codes.
    """
    ip = ratelimit.client_ip(request)
    ratelimit.check("enrolment_redeem", ip, ratelimit.ENROLMENT_REDEEM_PER_IP)
    try:
        result = await EnrolmentService(session).redeem(payload, ip)
    except AppError:
        # Every refusal this service raises is an AppError with its own code —
        # a code that does not exist, one already revoked, one already spent by
        # a different handset. All of them are guesses from here; which one it
        # was is the caller's business, not the limiter's.
        ratelimit.penalise("enrolment_redeem", ip, ratelimit.ENROLMENT_REDEEM_PER_IP)
        raise
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


@router.post("/verify/self", response_model=DeviceVerificationStatusOut)
async def verify_self_declared(
    installation: InstallationDep, session: SessionDep
) -> DeviceVerificationStatusOut:
    """Route 3 — finish on the strength of the enrolment code alone (§9.3).

    The two proving routes are frequently both unavailable on this fleet at
    once: Uzbek SIMs leave ``getLine1Number()`` empty, and the callback route
    needs an always-on receiver line. Before this existed such a handset had no
    path to ``active`` at all — it sat on E5 for ever and uploaded nothing,
    which is strictly worse than an enrolled phone with an unproven binding,
    because an unenrolled phone reports nothing and so nobody can see it is
    stuck.

    What it claims is narrow and is recorded as such: whoever held the
    single-use code an admin issued **for this one number** typed it into this
    handset. The installation is marked ``self_declared`` in its method, its
    funnel stage and an audit row, so the panel renders an unproven binding as
    unproven and an admin can attest it properly afterwards.

    409 ``self_declared_disabled`` when ``enrolment.allow_self_declared`` is
    off — a configuration answer rather than a retryable one, so the app sends
    the agent to an admin instead of offering the same button again.
    """
    tokens = await EnrolmentService(session).complete_self_declared_verification(
        installation
    )
    return DeviceVerificationStatusOut(
        state=VerificationState.SELF_DECLARED,
        status=installation.status,
        tokens=IssuedTokensOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
    )


@router.get("/status", response_model=DeviceVerificationStatusOut)
async def enrolment_status(
    installation: InstallationDep, session: SessionDep
) -> DeviceVerificationStatusOut:
    """Where this installation stands, and its tokens once it is active.

    **This is what makes admin attestation reach the phone.** Attesting
    activated the installation server-side, and the handset had no way to find
    out: the real token pair is minted at verification, so a phone waiting on
    an admin held a provisional token that expired while the thing it was
    waiting for had already happened. E5 polls this, so the agent's screen
    completes itself the moment an admin acts.

    Provisional token is enough — it must be, since a phone that is not active
    yet holds nothing else — and no tokens come back until the installation is
    active, whatever activated it.
    """
    installation, tokens = await EnrolmentService(session).enrolment_status(installation)
    if tokens is None:
        return DeviceVerificationStatusOut(
            state=VerificationState.PENDING, status=installation.status
        )
    return DeviceVerificationStatusOut(
        state=_state_for(installation.verification_method),
        status=installation.status,
        tokens=IssuedTokensOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
    )


def _state_for(method: VerificationMethod | None) -> VerificationState:
    """Which route finished, as the app's screen names it.

    The app renders an attested or self-declared binding differently from a
    proven one (SPEC §9.3), and the state is the only signal it gets here — so
    the mapping is explicit rather than "anything active is matched".
    """
    return {
        VerificationMethod.ADMIN_ATTESTED: VerificationState.ATTESTED,
        VerificationMethod.SELF_DECLARED: VerificationState.SELF_DECLARED,
    }.get(method, VerificationState.MATCHED)


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
