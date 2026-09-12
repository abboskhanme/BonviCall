"""MoiZvonki's webhook (T-MZ).

The provider posts ``call.start`` / ``call.answer`` / ``call.finish`` here.

═══ Two rules, both load-bearing ══════════════════════════════════════════
1. **A wrong secret answers 404, never 401.** The caller is anonymous by
   design, so the secret in the path IS the authentication; a 401 would
   confirm the endpoint exists to anyone scanning for it.
2. **Everything understood answers 200 — and so does everything not
   understood.** A 4xx makes the provider retry a payload that will never
   become valid, for ever. What is dropped is logged instead.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from src.core.deps import SessionDep
from src.core.errors import NotFoundError
from src.core.logging import get_logger
from src.modules.telephony.client import MoiZvonkiClient
from src.modules.telephony.rules import parse_event
from src.modules.telephony.service import TelephonyService

log = get_logger(__name__)

router = APIRouter(prefix="/api/telephony", tags=["Telephony webhook"])


@router.post(
    "/moizvonki/{secret}",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def moizvonki(secret: str, body: dict[str, Any], session: SessionDep) -> dict:
    """Accept one provider event.

    ``include_in_schema=False``: this is somebody else's contract, not ours,
    and publishing it in our OpenAPI would invite a client to be generated
    against a shape we do not control.
    """
    client = MoiZvonkiClient()
    if not client.is_configured or secret != client.webhook_secret:
        # Not an error the provider should retry, and not a fact a scanner
        # should learn.
        raise NotFoundError()

    event = parse_event(body)
    if event is None:
        log.info("moizvonki_event_ignored", fields=sorted(body.keys()))
        return {"accepted": False, "reason": "not a call event"}

    result = await TelephonyService(session).handle_event(event)
    return {"accepted": result.stored, "reason": result.reason}
