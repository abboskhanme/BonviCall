"""Device call ingest (T25, UC-12, SPEC §4.4).

**The whole of M1 hangs on this route.** Its contract:

* the batch is idempotent on the device's own ``client_call_id``, so a resend
  after a lost response produces no second row and the same server id;
* failure is **per item**, never per batch — a batch that fails wholesale is a
  batch the device retries forever;
* the response is always ``200``. A first write and a replay are
  indistinguishable to the client, which is exactly what UC-12 requires.

There is no version gate here on purpose (N34, SPEC §4.3): ingest accepts any
app version, forever. The refusal lives on ``POST /auth/refresh`` and fires only
once the phone's queue is empty.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.device.deps import ActiveInstallationDep
from src.core import clock
from src.core.deps import SessionDep
from src.modules.calls.schemas import DeviceCallBatchIn, DeviceCallBatchOut
from src.modules.calls.service import CallService

router = APIRouter(prefix="/calls", tags=["Device calls"])


@router.post("", response_model=DeviceCallBatchOut)
async def ingest_calls(
    payload: DeviceCallBatchIn,
    installation: ActiveInstallationDep,
    session: SessionDep,
) -> DeviceCallBatchOut:
    """Batch upsert, at most 50 items.

    ``number_id`` and ``agent_id`` are resolved from the installation and the
    time-boxed assignment — never from the payload. The device does not get to
    say which number it is, and it does not get to move a call to another agent
    by re-sending it.
    """
    results = await CallService(session).ingest(installation, payload.calls)
    return DeviceCallBatchOut(results=results, server_time=clock.now())
