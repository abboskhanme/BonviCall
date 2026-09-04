"""The device contract may not contain a free-form map (§8 rule 5, §15).

**The wire schema is the allow-list.** A field the contract does not name
cannot leave the phone, and the handset belongs to the employee. CONVENTIONS.md
§8 enforces the same boundary on the Android side with a type signature, so
that it cannot be widened in one line; this is the other end of the same pipe,
and an open map here is that same one-line widening.

A map whose *values* are typed is still open: the **keys** are unconstrained,
which is enough to carry anything off the device. That is exactly the shape
that shipped in ``DeviceEventIn.detail`` and was caught by the Android agent
generating DTOs, not by review — hence this test.

There is a matching ``DeviceContractPrivacyTest`` on the Android side reading
the same artefact. Two ends, one file, no exceptions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "openapi-device-v1.json"

#: Named exceptions, if any ever become necessary. Each needs a task id and a
#: date, and the list only shrinks. It is empty, and that is the point.
ALLOWED_OPEN_MAPS: dict[str, str] = {}


def _document() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _request_schema_names(document: dict) -> set[str]:
    """Every component schema reachable from a device **request** body."""
    names: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in names:
                    names.add(name)
                    walk(document["components"]["schemas"].get(name, {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for operations in document.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict) and "requestBody" in operation:
                walk(operation["requestBody"])
    return names


def _open_maps(schema: dict, path: str) -> list[str]:
    """Locations where a schema accepts keys it does not name."""
    found: list[str] = []
    if not isinstance(schema, dict):
        return found

    extra = schema.get("additionalProperties")
    if extra is True or isinstance(extra, dict):
        # additionalProperties: {"type": "string"} still leaves the keys open.
        found.append(path)

    for name, child in (schema.get("properties") or {}).items():
        found.extend(_open_maps(child, f"{path}.{name}"))
    for keyword in ("anyOf", "oneOf", "allOf"):
        for index, child in enumerate(schema.get(keyword) or []):
            found.extend(_open_maps(child, f"{path}[{keyword}{index}]"))
    if "items" in schema:
        found.extend(_open_maps(schema["items"], f"{path}[]"))
    return found


def test_the_device_contract_exists() -> None:
    assert CONTRACT.is_file(), "run `make contract`"


def test_no_device_request_schema_accepts_an_unnamed_field() -> None:
    """The rule, with no exceptions. ``ALLOWED_OPEN_MAPS`` is empty."""
    document = _document()
    schemas = document.get("components", {}).get("schemas", {})
    offenders: list[str] = []
    for name in sorted(_request_schema_names(document)):
        if name in ALLOWED_OPEN_MAPS:
            continue
        offenders.extend(_open_maps(schemas.get(name, {}), name))
    assert offenders == [], (
        "these device request fields accept keys the contract does not name: "
        f"{offenders}. Name every field, or the boundary is a promise rather "
        "than a type. (CONVENTIONS.md §8 rule 5, §15)"
    )


def test_the_event_detail_is_a_named_schema() -> None:
    """The specific field that shipped open, pinned so it cannot return."""
    schemas = _document()["components"]["schemas"]
    assert "DeviceEventDetailIn" in schemas
    detail = schemas["DeviceEventDetailIn"]
    assert detail.get("additionalProperties") is False, (
        "extra='forbid' must reach the contract, or a client can still send "
        "an unnamed field and be quietly accepted"
    )
    assert detail["properties"], "a named schema with no named fields is a map"


@pytest.mark.parametrize(
    "field",
    ["queue_records", "client_call_id", "capture_route", "discarded_count"],
)
def test_the_event_detail_names_what_the_events_actually_carry(field: str) -> None:
    """If a field is missing the app cannot report it — and it will be added
    here, in a diff, rather than smuggled through an open map."""
    schemas = _document()["components"]["schemas"]
    assert field in schemas["DeviceEventDetailIn"]["properties"]
