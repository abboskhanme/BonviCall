"""The MoiZvonki REST client (T-MZ).

Ported from the WunderkindLC integration, which runs in production against the
same provider. Kept deliberately thin: one POST shape, one place that knows the
credentials, and no business logic — the mapping from a provider event to a
BonviCall row lives in :mod:`src.modules.telephony.service`, where it can be
tested without a network.

═══ The provider's shape ══════════════════════════════════════════════════
``POST https://{domain}.moizvonki.ru/api/v1`` with a JSON body carrying the
credentials **in the body** rather than a header:

    {"user_name": ..., "api_key": ..., "action": ..., ...}

``action`` selects the operation. The three this product uses:

* ``calls.make_call`` — ring the operator's own handset, then the number
  (click-to-call, UC-16);
* ``webhook.subscribe`` — point ``call.start`` / ``call.answer`` /
  ``call.finish`` at our endpoint;
* ``calls.list`` — the history sweep, for the events a phone with no signal
  never delivered.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger(__name__)

#: Twenty seconds. The provider answers in well under a second when it is
#: healthy; a longer timeout only holds a worker while a call goes unanswered.
TIMEOUT_SECONDS = 20.0


class MoiZvonkiClient:
    """Talks to one MoiZvonki cabinet.

    Construct per request rather than as a singleton: it holds no connection
    state worth reusing, and reading the settings each time means a credential
    change takes effect on the next call rather than on the next restart.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.moizvonki_enabled
        self.domain = settings.moizvonki_domain.strip()
        self.username = settings.moizvonki_username.strip()
        self.api_key = settings.moizvonki_api_key.get_secret_value()
        self.webhook_secret = settings.moizvonki_webhook_secret.get_secret_value()

    @property
    def is_configured(self) -> bool:
        """Every part present. A half-configured integration must not run: it
        would fail one call at a time and look like a provider outage."""
        return bool(
            self.enabled and self.domain and self.username and self.api_key
        )

    @property
    def api_url(self) -> str:
        """A bare name becomes ``{name}.moizvonki.ru``; anything containing a
        dot or a scheme is used as given, which is what lets a test point the
        client at a local stub."""
        if self.domain.startswith(("http://", "https://")):
            return f"{self.domain.rstrip('/')}/api/v1"
        host = self.domain if "." in self.domain else f"{self.domain}.moizvonki.ru"
        return f"https://{host}/api/v1"

    async def call_api(
        self, action: str, **extra: Any
    ) -> tuple[bool, dict[str, Any] | str]:
        """One request. Returns ``(ok, parsed-body-or-error-text)``.

        Never raises across this boundary. Every caller here is either a
        webhook handler — which must answer 200 so the provider stops retrying
        — or a scheduled job, which must not die on somebody else's outage.
        """
        if not self.is_configured:
            return False, "moizvonki is not configured"

        payload: dict[str, Any] = {
            "user_name": self.username,
            "api_key": self.api_key,
            "action": action,
            **extra,
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
                response = await http.post(self.api_url, json=payload)
        except httpx.HTTPError as error:
            log.warning("moizvonki_unreachable", action=action, error=str(error))
            return False, f"could not reach the provider: {error}"

        if response.status_code >= 400:
            # The body, not just the status: the provider explains refusals in
            # it, and "HTTP 400" on its own has sent people looking in the
            # wrong place before.
            log.warning(
                "moizvonki_refused",
                action=action,
                status=response.status_code,
                body=response.text[:500],
            )
            return False, response.text or f"HTTP {response.status_code}"

        try:
            return True, response.json()
        except ValueError:
            return True, response.text

    async def make_call(self, to_number: str) -> tuple[bool, dict[str, Any] | str]:
        """Click-to-call: the provider rings the operator's handset first, then
        dials ``to_number`` from it."""
        return await self.call_api("calls.make_call", to=to_number)

    async def subscribe_webhooks(self, url: str) -> tuple[bool, dict[str, Any] | str]:
        """Point the three call events at ``url``.

        Several field shapes are sent together because the provider's schema
        has varied between cabinets and the extra keys are ignored where they
        are not understood — the same belt-and-braces the WunderkindLC
        integration settled on after the first subscription silently did
        nothing.
        """
        events = ["call.start", "call.answer", "call.finish"]
        return await self.call_api(
            "webhook.subscribe",
            url=url,
            events=events,
            **{event: url for event in events},
        )

    async def list_calls(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> tuple[bool, dict[str, Any] | str]:
        """The history sweep. Dates are the provider's own format and are
        passed through rather than reformatted here."""
        extra: dict[str, Any] = {}
        if date_from:
            extra["date_from"] = date_from
        if date_to:
            extra["date_to"] = date_to
        return await self.call_api("calls.list", **extra)
