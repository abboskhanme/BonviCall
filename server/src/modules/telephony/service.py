"""Turning a MoiZvonki event into a BonviCall call row (T-MZ).

═══ It does not write the row itself ══════════════════════════════════════
It builds a :class:`DeviceCallIn` and hands it to the existing
:meth:`CallService.ingest`. That is the whole design decision in this file.
Ingest already does attribution against the assignment covering the call,
duplicate detection on ``client_call_id``, the identity-conflict alert, the
line directory and the out-of-range guard — and every one of those has to
behave the same whether a call came from a handset or from a provider. A second
ingest path would be a second set of rules, and the day they disagreed the
symptom would be calls attributed to the wrong salesperson.

═══ The provider needs an installation, and has no device ═════════════════
``calls.installation_id`` is ``NOT NULL``: every call is delivered by
something. For a provider call that something is the cabinet, so each
registered number gets one **provider installation** — a synthetic device row
and an installation marked ``self_declared``. It is created once, lazily, and
reused.

This is honest rather than a workaround: the installation is "what delivers
calls for this number", and here it genuinely is the provider. It also means
the panel, the reports, RBAC scoping and the gap report keep working with no
change at all — a provider line simply appears alongside the handsets.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.enums import CallSource
from src.core.logging import get_logger
from src.core.phone import phone_key
from src.core.security import sha256_hex
from src.modules.calls.schemas import DeviceCallIn
from src.modules.calls.service import CallService
from src.modules.installations.service import InstallationService
from src.modules.numbers.service import NumberService
from src.modules.telephony.rules import (
    ProviderEvent,
    answered_at_for,
    client_call_id_for,
    disposition_for,
)

log = get_logger(__name__)

class TelephonyIngestResult:
    """Why an event did or did not become a row. Returned rather than raised:
    the webhook must answer 200 to everything, or the provider retries for
    ever."""

    def __init__(self, stored: bool, reason: str) -> None:
        self.stored = stored
        self.reason = reason


class TelephonyService:
    """Ingest for the cloud-telephony source."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.numbers = NumberService(session)
        self.installations = InstallationService(session)

    async def handle_event(self, event: ProviderEvent) -> TelephonyIngestResult:
        """One webhook event.

        Only the finish event produces a row. ``call.start`` and
        ``call.answer`` are acknowledged and dropped: neither carries a
        disposition or a duration, and a row written from them would have to be
        corrected by the finish event anyway — which is exactly the
        half-written state ``client_call_id`` exists to avoid.
        """
        if not event.is_final:
            return TelephonyIngestResult(False, "not a finish event")

        number = await self._resolve_number(event)
        if number is None:
            # ⚠️ Never guessed. Attributing a call to the wrong salesperson is
            # the one mistake this product cannot recover from, and the sweep
            # (`calls.list`) will find the call again once the mapping is
            # known. The raw keys are logged so the cabinet's own field name
            # can be read off a real event.
            log.warning(
                "moizvonki_unattributable",
                pbx_call_id=event.pbx_call_id,
                operator_hint=event.operator_hint,
                event_fields=list(event.raw_keys),
            )
            return TelephonyIngestResult(False, "no registered number matched")

        installation = await self._provider_installation(number)
        item = self._to_call(event, installation)
        results = await CallService(self.session).ingest(installation, [item])
        await self.session.commit()

        failed = [r for r in results if getattr(r, "error", None) is not None]
        if failed:
            return TelephonyIngestResult(False, "ingest refused the row")
        return TelephonyIngestResult(True, "stored")

    # --- Attribution -------------------------------------------------------

    async def _resolve_number(self, event: ProviderEvent):
        """Which of OUR lines was this call on?

        Only the operator hint answers it. ``client_number`` is the other party
        and must never be used for this: on an incoming call it is the client's
        number, and matching a registered line against it would file the call
        under whichever salesperson happened to share digits with a customer.

        The lookup goes through ``NumberService`` rather than a SELECT here —
        ``registered_numbers`` belongs to that module, and two modules
        normalising "the same number" is how a match becomes a coin toss (§2).
        """
        if not event.operator_hint:
            return None
        key = phone_key(event.operator_hint)
        if key is None:
            return None
        return await self.numbers.by_phone_key(key)

    async def _provider_installation(self, number):
        """The cabinet's stand-in for a handset on this line.

        Created by ``InstallationService``, which owns ``installations`` and
        ``devices``: a second module writing those rows is the layering the
        architecture test refuses, and it refuses it because installation
        creation carries rules a parallel creator would not.

        The fingerprint is derived from the number rather than random, so a
        restart cannot produce a second installation for the same line and
        split one salesperson's history in two.
        """
        assignment = await self.numbers.holder_at(number.id, clock.now())
        if assignment is None:
            raise ValueError(
                f"registered number {number.id} has no agent; cannot ingest a call"
            )
        return await self.installations.provider_installation(
            number_id=number.id,
            agent_id=assignment.agent_id,
            fingerprint=sha256_hex(f"moizvonki:{number.id}"),
        )

    # --- Mapping -----------------------------------------------------------

    def _to_call(self, event: ProviderEvent, installation) -> DeviceCallIn:
        """The provider's event as the ingest path expects it.

        ``ended_at`` is the moment the webhook arrived rather than a field of
        the event: the provider sends no end timestamp, and the finish event
        arrives within seconds of the call ending. ``started_at`` is then the
        end less the duration, which is the only internally consistent pair
        available — inventing a more precise start would be a number nobody
        measured.
        """
        ended_at = clock.now()
        answered_at = answered_at_for(event, ended_at)
        started_at = answered_at or ended_at

        return DeviceCallIn(
            client_call_id=client_call_id_for(event.pbx_call_id),
            direction=event.direction,
            disposition=disposition_for(event),
            remote_number=event.client_number or None,
            started_at=started_at,
            answered_at=answered_at,
            ended_at=ended_at,
            duration_sec=event.duration_sec,
            source=CallSource.PROVIDER,
            # The cabinet holds the recording. Whether it is fetched is the
            # audio pipeline's decision, not this one's — but the row must not
            # claim audio it has not stored, so the expectation is recorded and
            # the file is pulled separately.
            audio_expected=event.recording_url is not None,
            device_epoch_ms=int(ended_at.timestamp() * 1_000),
            device_timezone=clock.TASHKENT.key,
            app_version=None,
            app_variant=None,
        )


def provider_call_uuid(pbx_call_id: str) -> uuid.UUID:
    """Re-exported so the sweep and the tests do not import the rules module
    for one function."""
    return client_call_id_for(pbx_call_id)
