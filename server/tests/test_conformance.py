"""T106: the response conventions, checked across every endpoint at once.

Two rules from SPEC §4.0 that are easy to hold per module and easy to break
across one: **every list has the same shape**, and **every error has the same
envelope**. Both are the kind of thing a reviewer checks on the module in front
of them and nobody checks on the whole surface, which is why this walks the
generated contract instead of a list somebody maintains.
"""

from __future__ import annotations

import pytest

from src.contract_export import build_documents

pytestmark = pytest.mark.asyncio

#: SPEC §4.0. A list carries its rows and how many there are; cursor-paginated
#: ones add ``next_cursor``. Anything calling itself a list and shaped
#: differently makes the panel special-case it.
LIST_REQUIRED = {"items", "total"}

#: Collection responses that are deliberately not ``items``/``total``.
#: Each one is a *report*, not a list of rows — its shape is the answer to a
#: question, and forcing it into a list envelope would be worse.
NOT_A_LIST = {
    "StorageReportResponse",  # a curve plus today's totals
    "GapReportResponse",  # a rate, with its numerator and denominator
    "ReceiverStatusResponse",
    "DeviceCapabilityBatchOut",
    "DeviceEventBatchOut",
    "DeviceCommandListOut",  # device wire: a batch, no total to page through
    "DeviceCallLogDeltaOut",
    "ImportAgentsResponse",
    "OpenDeltaOut",
}


def _schemas(stem: str) -> dict:
    return build_documents()[stem].get("components", {}).get("schemas", {})


@pytest.mark.parametrize(
    "stem", ["openapi-panel-v1", "openapi-device-v1", "openapi-service-v1"]
)
async def test_every_list_response_has_the_same_shape(stem: str) -> None:
    """A ``*ListResponse`` that is not ``items`` + ``total`` is a special case
    the panel has to learn, and it will learn it once per page."""
    offenders = []
    for name, schema in _schemas(stem).items():
        if not name.endswith(("ListResponse", "ListOut")) or name in NOT_A_LIST:
            continue
        properties = set(schema.get("properties") or {})
        if not LIST_REQUIRED <= properties:
            offenders.append(f"{name}: {sorted(properties)}")
    assert offenders == [], (
        f"list responses missing {sorted(LIST_REQUIRED)}: {offenders}. Either "
        "give them the shape, or add them to NOT_A_LIST with the reason they "
        "are a report rather than a list."
    )


async def test_the_not_a_list_exceptions_all_still_exist() -> None:
    """A stale exception hides the next real one."""
    live = set()
    for stem in ("openapi-panel-v1", "openapi-device-v1", "openapi-service-v1"):
        live |= set(_schemas(stem))
    stale = sorted(NOT_A_LIST - live)
    assert stale == [], f"listed but no longer on the wire: {stale}"


ENVELOPE_KEYS = {"code", "message", "request_id"}


async def test_every_error_shape_is_the_same_envelope(
    client, admin, sales, installation_factory
) -> None:
    """N35: one envelope, whatever went wrong and wherever.

    Driven through real requests rather than the document, because FastAPI only
    documents the error responses a route declares — and the ones that matter
    here are the ones nobody declared. 401, 403, 404, 405, 409, 422 and the
    unrouted 404 all come from different handlers, which is exactly why they
    could drift apart.
    """
    installation = await installation_factory()
    cases = {
        "401 no token": await client.get("/api/v1/calls"),
        "403 wrong role": await sales.get("/api/v1/users"),
        "404 missing row": await admin.get(
            "/api/v1/calls/00000000-0000-0000-0000-000000000000"
        ),
        "404 unrouted path": await admin.get("/api/v1/no-such-thing"),
        "405 wrong method": await admin.delete(
            f"/api/v1/calls/{installation.id}"
        ),
        "422 bad body": await admin.post("/api/v1/agents", json={"full_name": ""}),
    }
    for label, response in cases.items():
        body = response.json()
        assert "error" in body, f"{label}: not an envelope — {body}"
        assert ENVELOPE_KEYS <= set(body["error"]), f"{label}: {sorted(body['error'])}"
        assert isinstance(body["error"]["code"], str), label
        assert body["error"]["message"], f"{label}: empty message"


async def test_the_device_surface_uses_the_same_envelope(client) -> None:
    """The phone parses errors too, and it branches on ``code`` (§4.0)."""
    for response in (
        await client.get("/api/device/v1/commands"),
        await client.post("/api/device/v1/calls", json={"calls": []}),
    ):
        body = response.json()
        assert ENVELOPE_KEYS <= set(body["error"]), body
