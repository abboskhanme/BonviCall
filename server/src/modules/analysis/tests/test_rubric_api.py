"""The rubric endpoints: RBAC, the refusal, and what the editor reads.

The claims this file is responsible for:

* every route answers **401** without a token and **403** for a role that does
  not hold the permission (CONVENTIONS.md §13);
* **a non-admin cannot edit.** ``manager`` reads the rubric and is refused on
  both write routes — the same line the registry draws at ``settings:write``:
  a change here alters how everybody is scored from then on, and is paid for on
  every call;
* a rubric whose blocks do not total 100 comes back **422 with a machine
  reason** and is **not saved** — the read afterwards still shows the old one;
* an unseeded database answers 200 with the rubric pinned in code rather than
  404, because that rubric is what such a database really scores with.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.modules.analysis.rubric_default import DEFAULT_RUBRIC

pytestmark = pytest.mark.asyncio

RUBRIC_URL = "/api/v1/analysis/rubric"
VERSIONS_URL = f"{RUBRIC_URL}/versions"
PROMPT_URL = f"{RUBRIC_URL}/prompt"


def payload(**overrides: Any) -> dict[str, Any]:
    """A rubric the validator accepts: three blocks, 40 + 35 + 25 = 100.

    English labels — Uzbek in a ``.py`` file is legal in six files and this is
    not one of them (CONVENTIONS.md §14). The language of a label is data and
    no assertion here is about it.
    """
    body: dict[str, Any] = {
        "name": "Published from a test",
        "description": None,
        "blocks": [
            {
                "key": "script",
                "label": "Script",
                "max": 40,
                "criteria": [
                    {"id": "A1", "label": "Greeting", "points": 15, "optional": False},
                    {"id": "A2", "label": "Needs", "points": 25, "optional": True},
                ],
            },
            {
                "key": "manner",
                "label": "Manner",
                "max": 35,
                "criteria": [
                    {"id": "B1", "label": "Respect", "points": 35, "optional": False}
                ],
            },
            {
                "key": "closing",
                "label": "Closing",
                "max": 25,
                "criteria": [
                    {"id": "C1", "label": "Next step", "points": 25, "optional": False}
                ],
            },
        ],
        "red_flags": [
            {
                "type": "shouting",
                "label": "Shouting",
                "penalty": -20,
                "zeroes_score": False,
                "description": None,
            }
        ],
        "extra_rules": None,
    }
    body.update(overrides)
    return body


# --- RBAC ------------------------------------------------------------------


async def test_every_route_is_401_without_a_token(client) -> None:
    assert (await client.get(RUBRIC_URL)).status_code == 401
    assert (await client.get(VERSIONS_URL)).status_code == 401
    assert (await client.get(PROMPT_URL)).status_code == 401
    assert (await client.put(RUBRIC_URL, json=payload())).status_code == 401
    assert (await client.post(f"{VERSIONS_URL}/1/activate")).status_code == 401


async def test_a_manager_reads_the_rubric_and_cannot_change_it(manager) -> None:
    """**A non-admin cannot edit.**

    A manager reviews calls and must be able to see the criteria a score was
    produced against — a score whose rubric is invisible is a number nobody can
    argue with. Publishing is another thing: it decides how everybody is scored
    afterwards, and its text is paid for on every call.
    """
    assert (await manager.get(RUBRIC_URL)).status_code == 200
    assert (await manager.get(VERSIONS_URL)).status_code == 200
    assert (await manager.get(PROMPT_URL)).status_code == 200

    refused = await manager.put(RUBRIC_URL, json=payload())
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"
    assert (await manager.post(f"{VERSIONS_URL}/1/activate")).status_code == 403


async def test_sales_cannot_read_the_rubric_at_all(sales) -> None:
    """``analysis:read`` is withheld from ``sales`` on purpose (§12 Q1), and the
    criteria their own score is produced against are part of that decision."""
    assert (await sales.get(RUBRIC_URL)).status_code == 403
    assert (await sales.put(RUBRIC_URL, json=payload())).status_code == 403


async def test_a_service_token_is_refused_everywhere(service_token) -> None:
    """The export contract (SPEC §4.9) is frozen, and the rubric is not in it."""
    assert (await service_token.get(RUBRIC_URL)).status_code == 403
    assert (await service_token.put(RUBRIC_URL, json=payload())).status_code == 403


# --- Reading ---------------------------------------------------------------


async def test_an_unseeded_database_answers_with_the_rubric_pinned_in_code(
    admin,
) -> None:
    """200 and ``stored: false``, never 404.

    404 would mean "there is no rubric", and there is one: it is the constant,
    and it is what this database scores with until somebody publishes.
    """
    body = (await admin.get(RUBRIC_URL)).json()

    assert body["stored"] is False
    assert body["id"] is None
    assert (body["version"], body["label"], body["is_active"]) == (1, "v1", True)
    assert [block["key"] for block in body["blocks"]] == [
        item["key"] for item in DEFAULT_RUBRIC["blocks"]
    ]
    assert body["extra_rules"] is None


async def test_the_version_history_is_empty_until_something_is_published(
    admin,
) -> None:
    body = (await admin.get(VERSIONS_URL)).json()
    assert body == {"items": [], "total": 0}


async def test_the_prompt_preview_shows_what_the_model_receives(admin) -> None:
    """Read-only, and only the admin's own section is marked editable.

    The rest is the language rules, the scoring order and the response format:
    break any of them and every answer fails validation, so one edit would stop
    all scoring.
    """
    body = (await admin.get(PROMPT_URL)).json()

    assert body["rubric_label"] == "v1"
    assert body["char_count"] == len(body["full_text"])
    editable = [section["key"] for section in body["sections"] if section["editable"]]
    assert editable == ["extra_rules"]


# --- Publishing ------------------------------------------------------------


async def test_publishing_returns_the_new_version_and_it_becomes_the_active_one(
    admin,
) -> None:
    created = await admin.put(RUBRIC_URL, json=payload(name="First"))

    assert created.status_code == 200
    body = created.json()
    assert (body["version"], body["label"], body["stored"]) == (1, "v1", True)
    assert body["name"] == "First"
    assert body["id"] is not None

    # And the next read is the same rubric, from the table this time.
    active = (await admin.get(RUBRIC_URL)).json()
    assert (active["version"], active["stored"]) == (1, True)
    assert [block["key"] for block in active["blocks"]] == ["script", "manner", "closing"]


async def test_publishing_twice_leaves_the_first_version_in_the_history(
    admin,
) -> None:
    await admin.put(RUBRIC_URL, json=payload(name="First"))
    await admin.put(RUBRIC_URL, json=payload(name="Second", extra_rules="be brief"))

    history = (await admin.get(VERSIONS_URL)).json()
    assert history["total"] == 2
    assert [item["label"] for item in history["items"]] == ["v2", "v1"]
    assert [item["is_active"] for item in history["items"]] == [True, False]
    assert (await admin.get(RUBRIC_URL)).json()["extra_rules"] == "be brief"


async def test_a_rubric_that_does_not_total_one_hundred_is_refused_and_not_saved(
    admin,
) -> None:
    """The rule that survived the port, asserted through the wire.

    The refusal carries a machine ``reason`` and the numbers; the panel renders
    the Uzbek sentence from ``uz.json``, so no payload and no column ever holds
    display copy (§1.6).
    """
    await admin.put(RUBRIC_URL, json=payload(name="First"))

    short = payload(name="Second")
    short["blocks"][0]["max"] = 35
    short["blocks"][0]["criteria"][1]["points"] = 20

    refused = await admin.put(RUBRIC_URL, json=short)

    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "validation_error"
    assert error["detail"] == {
        "reason": "rubric_total_not_100",
        "total": 95,
        "expected": 100,
    }
    # Not saved: still one version, and it is still the one that was working.
    assert (await admin.get(VERSIONS_URL)).json()["total"] == 1
    assert (await admin.get(RUBRIC_URL)).json()["name"] == "First"


async def test_a_red_flag_key_the_model_cannot_echo_back_is_refused(admin) -> None:
    body = payload()
    body["red_flags"][0]["type"] = "shouting loudly"

    refused = await admin.put(RUBRIC_URL, json=body)

    assert refused.status_code == 422
    assert refused.json()["error"]["detail"]["reason"] == "rubric_flag_key_invalid"


async def test_a_penalty_that_awards_points_is_refused_by_the_schema(admin) -> None:
    """``penalty`` is ``le=0`` on the wire as well as in the service.

    Two checks for one rule on purpose: the wire contract documents it for every
    client, and the service is where the rule lives for every caller.
    """
    body = payload()
    body["red_flags"][0]["penalty"] = 20

    refused = await admin.put(RUBRIC_URL, json=body)

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_error"


async def test_extra_rules_longer_than_the_cap_are_refused(admin) -> None:
    """That text rides on every call, so its length is money."""
    refused = await admin.put(RUBRIC_URL, json=payload(extra_rules="x" * 4001))
    assert refused.status_code == 422


# --- Going back ------------------------------------------------------------


async def test_activating_an_earlier_version_makes_it_active_again(admin) -> None:
    await admin.put(RUBRIC_URL, json=payload(name="First"))
    await admin.put(RUBRIC_URL, json=payload(name="Second"))

    restored = await admin.post(f"{VERSIONS_URL}/1/activate")

    assert restored.status_code == 200
    assert restored.json()["version"] == 1
    assert (await admin.get(RUBRIC_URL)).json()["name"] == "First"


async def test_activating_a_version_that_was_never_published_is_404(admin) -> None:
    missing = await admin.post(f"{VERSIONS_URL}/7/activate")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
