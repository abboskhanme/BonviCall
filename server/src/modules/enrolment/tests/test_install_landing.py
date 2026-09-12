"""The install landing page (UC-02, SPEC §8.1).

It is the first thing a non-technical salesperson touches, on their own phone,
over mobile data, inside N40's fifteen minutes. So: no JavaScript, a few
kilobytes, Uzbek, and one button.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape

import pytest

from src.core import ratelimit
from src.core.enums import AppVariant
from src.core.messages_uz import INSTALL_PAGE
from src.modules.catalog.models import AppVersionModel

pytestmark = pytest.mark.asyncio

ANDROID_13_UA = (
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
)


@pytest.fixture(autouse=True)
def _clean_limits():
    """The limiter is process-wide, so a shared counter would leak between tests."""
    ratelimit.reset()
    yield
    ratelimit.reset()


async def _publish_apk(db) -> None:
    db.add(
        AppVersionModel(
            version="1.0.0",
            version_code=100,
            variant=AppVariant.MODERN34,
            apk_path="releases/bonvicall-1.0.0.apk",
            apk_sha256="c" * 64,
            size_bytes=28_000_000,
            published_at=datetime.now(UTC),
            is_current=True,
        )
    )
    await db.flush()


async def test_the_page_is_html_and_needs_no_javascript(
    db, client, enrolment_code_factory
) -> None:
    await _publish_apk(db)
    code = await enrolment_code_factory()
    response = await client.get(f"/i/{code.code}", headers={"User-Agent": ANDROID_13_UA})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<script" not in response.text, "it must work with JavaScript off"
    assert len(response.content) < 8_000, "it is downloaded over mobile data"


async def test_the_page_names_the_agent_and_the_number_being_recorded(
    db, client, enrolment_code_factory, agent_factory, registered_number_factory
) -> None:
    """N41 starts here: the number is on screen before anything is installed."""
    await _publish_apk(db)
    agent = await agent_factory(full_name="Aziz Karimov")
    number = await registered_number_factory(agent=agent, e164="+998901112233")
    code = await enrolment_code_factory(agent=agent, number=number)

    text = (await client.get(f"/i/{code.code}")).text
    assert "Aziz Karimov" in text
    assert "+998 90 111-22-33" in text
    assert code.code in text


async def test_the_page_states_the_privacy_boundary(
    db, client, enrolment_code_factory
) -> None:
    """The handset is the employee's; the boundary is stated, not implied.

    Asserted against the catalogue, not against a copy of the sentence: the
    wording is the catalogue's to change, and §14 keeps Uzbek out of this file.
    """
    await _publish_apk(db)
    code = await enrolment_code_factory()
    text = (await client.get(f"/i/{code.code}")).text
    assert INSTALL_PAGE["boundary_second_sim"] in text
    assert INSTALL_PAGE["boundary_private"] in text


async def test_the_page_warns_about_play_protect_in_advance(
    db, client, enrolment_code_factory
) -> None:
    """R17: an unexpected warning is where an unaided enrolment stops."""
    await _publish_apk(db)
    code = await enrolment_code_factory()
    assert "Play Protect" in (await client.get(f"/i/{code.code}")).text


async def test_a_wrong_code_and_an_expired_code_are_indistinguishable(
    client, enrolment_code_factory
) -> None:
    """Useful to the agent, equally useful to somebody working through codes."""
    expired = await enrolment_code_factory(
        expires_at=datetime.now(UTC) - timedelta(hours=1)
    )
    wrong = await client.get("/i/ZZZZ9999")
    stale = await client.get(f"/i/{expired.code}")

    assert wrong.status_code == stale.status_code == 404
    assert wrong.text == stale.text
    # Escaped, because the page escapes everything it renders — an
    # apostrophe in Uzbek comes out as &#x27; and that is correct.
    assert escape(INSTALL_PAGE["unavailable_action"]) in wrong.text
    assert "expired" not in wrong.text.lower()


async def test_a_redeemed_code_stops_working(db, client, enrolment_code_factory) -> None:
    code = await enrolment_code_factory(redeemed_at=datetime.now(UTC))
    assert (await client.get(f"/i/{code.code}")).status_code == 404


async def test_the_download_link_redirects_to_the_published_build(
    db, client, enrolment_code_factory
) -> None:
    await _publish_apk(db)
    code = await enrolment_code_factory()
    response = await client.get(f"/i/{code.code}/apk", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/api/v1/app/download/100"


async def test_without_a_published_build_the_page_says_so_in_uzbek(
    client, enrolment_code_factory
) -> None:
    """A dead button is worse than a sentence."""
    code = await enrolment_code_factory()
    page = await client.get(f"/i/{code.code}")
    assert escape(INSTALL_PAGE["apk_not_ready_short"]) in page.text
    apk = await client.get(f"/i/{code.code}/apk", follow_redirects=False)
    assert apk.status_code == 404
    assert escape(INSTALL_PAGE["apk_missing_title"]) in apk.text


async def test_the_page_is_rate_limited(db, client, enrolment_code_factory) -> None:
    """It is public and it fronts a binary."""
    await _publish_apk(db)
    code = await enrolment_code_factory()
    limit = ratelimit.INSTALL_PAGE_PER_IP.requests
    for _ in range(limit):
        assert (await client.get(f"/i/{code.code}")).status_code == 200
    refused = await client.get(f"/i/{code.code}")
    assert refused.status_code == 429
    assert refused.headers["Retry-After"]


async def test_the_apk_link_is_limited_more_tightly_than_the_page(db) -> None:
    assert (
        ratelimit.APK_DOWNLOAD_PER_IP.requests < ratelimit.INSTALL_PAGE_PER_IP.requests
    )


async def test_the_page_needs_no_token(db, client, enrolment_code_factory) -> None:
    """PUBLIC_ROUTES carries it: the code in the URL is the only secret."""
    await _publish_apk(db)
    code = await enrolment_code_factory()
    assert "authorization" not in {k.lower() for k in client.headers}
    assert (await client.get(f"/i/{code.code}")).status_code == 200


async def test_the_deep_link_carries_the_server_the_page_was_served_from(
    db, client, enrolment_code_factory
) -> None:
    """Without this the app has no way to learn its own server.

    A release build refuses a typed address on purpose, so the deep link is the
    only channel there is. It carried the code alone for the whole of release 1,
    which pinned every release APK to the host compiled into it and left the
    app's own `?server=` reader with nothing to read.
    """
    await _publish_apk(db)
    code = await enrolment_code_factory()
    response = await client.get(
        f"/i/{code.code}",
        headers={
            "User-Agent": ANDROID_13_UA,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "call.bonvi.uz",
        },
    )

    assert response.status_code == 200
    assert "bonvicall://enrol?code=" in response.text
    assert "server=https%3A%2F%2Fcall.bonvi.uz" in response.text


async def test_the_deep_link_prefers_the_forwarded_host_over_the_internal_one(
    db, client, enrolment_code_factory
) -> None:
    """Behind a reverse proxy the app server's own view of the URL is useless.

    It sees cleartext HTTP on an internal name; handing that to the phone is an
    address that resolves nowhere and that the client's network config refuses
    for being cleartext before it is even tried.
    """
    await _publish_apk(db)
    code = await enrolment_code_factory()
    response = await client.get(
        f"/i/{code.code}",
        headers={
            "User-Agent": ANDROID_13_UA,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "call.bonvi.uz",
        },
    )

    link = response.text.split("bonvicall://")[1].split('"')[0]
    # Stated positively. Written as two "not in" assertions this passed with no
    # `server=` parameter at all — a test that holds because the thing it
    # guards is absent is the quiet lie this repository keeps finding.
    assert "server=https%3A%2F%2Fcall.bonvi.uz" in link
    assert "backend" not in link
    assert "server=http%3A%2F%2F" not in link


async def test_without_a_proxy_the_deep_link_uses_the_address_actually_used(
    db, client, enrolment_code_factory
) -> None:
    """A LAN or tunnel install has no forwarded headers and must still work."""
    await _publish_apk(db)
    code = await enrolment_code_factory()
    response = await client.get(
        f"/i/{code.code}",
        headers={"User-Agent": ANDROID_13_UA, "Host": "192.168.1.23:8020"},
    )

    assert "server=" in response.text
    assert "192.168.1.23" in response.text
