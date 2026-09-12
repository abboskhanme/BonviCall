"""The install landing page, rendered server-side (UC-02, SPEC §8.1).

**Why HTML and not the panel's React route.** This is the first thing a
non-technical salesperson touches, on their own phone, over mobile data, at the
moment N40 allows fifteen minutes unaided and R17 names installation the top
practical risk. A bundle costs a download before they see a word and fails to a
blank screen. This page works with JavaScript off, weighs a few kilobytes, and
hands over the APK.

Every Uzbek sentence lives in ``core/messages_uz.py`` (§14). This module owns
the markup and the layout decisions; it owns no wording.

**What it must not say.** An invalid code and an expired code get the same page
and the same next action. The distinction is useful to the agent and equally
useful to somebody guessing codes, and only one of them is entitled to it.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from src.core.messages_uz import INSTALL_PAGE as TEXT
from src.modules.enrolment.rules import display_number

#: Per-OEM install guidance is filled in by T107 from photographs of the real
#: screens. Until then the wording is version-generic, which is honest: a guess
#: at a screen path is worse than none.
HINT_KEYS = {"13+": "hint_android_13", "8-12": "hint_android_8"}


def _android_bucket(user_agent: str | None) -> str:
    """Very rough Android version bucket, from the User-Agent.

    Rough on purpose: the page shows one extra paragraph either way and names
    the other, so a wrong guess costs a sentence, not an enrolment.
    """
    if not user_agent or "Android" not in user_agent:
        return "8-12"
    fragment = user_agent.split("Android", 1)[1].strip(" ;")
    major = fragment.split(".", 1)[0].split(" ", 1)[0]
    try:
        return "13+" if int(major) >= 13 else "8-12"
    except ValueError:
        return "8-12"


_STYLE = (
    "body{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:20px;"
    "max-width:520px;line-height:1.5;color:#111}"
    "h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 6px}"
    ".num{font-size:22px;font-weight:600;letter-spacing:.5px}"
    ".btn{display:block;background:#6366f1;color:#fff;text-align:center;"
    "padding:14px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0}"
    ".code{font-family:monospace;font-size:20px;letter-spacing:3px;background:#f4f4f5;"
    "padding:8px 12px;border-radius:6px;display:inline-block}"
    "ul{padding-left:18px}li{margin:6px 0}.muted{color:#555;font-size:14px}"
)


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="uz"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def render_invitation(
    agent_name: str,
    number_e164: str,
    code: str,
    user_agent: str | None,
    apk_available: bool,
    server_base: str | None = None,
) -> str:
    """The page an agent opens from the link their admin sent them.

    ``server_base`` is the origin this page was served from, and it is carried
    into the deep link as ``&server=``. The app reads that parameter and it is
    the ONLY way a release build can be pointed at a server: a typed address is
    refused there on purpose (``ServerAddress`` — a field that repoints a
    salesperson's handset would send every call they make elsewhere). Omitting
    it left every release build pinned to the compiled-in production host,
    which is a deployment that cannot be moved and an app whose deep-link
    reader had nothing to read.
    """
    bucket = _android_bucket(user_agent)
    hint = TEXT[HINT_KEYS[bucket]]
    other = TEXT[HINT_KEYS["8-12" if bucket == "13+" else "13+"]]
    download = (
        f'<a class="btn" href="/i/{escape(code)}/apk">'
        f"{escape(TEXT['download_button'])}</a>"
        if apk_available
        else f'<p class="muted">{escape(TEXT["apk_not_ready_short"])}</p>'
    )
    # The code is the secret and the server is an address; both are query
    # values, so both are percent-encoded rather than trusted to be URL-safe.
    deep_link = f"bonvicall://enrol?code={quote(code, safe='')}"
    if server_base:
        deep_link += f"&server={quote(server_base, safe='')}"

    # The boundary bullets carry <b> from the catalogue, so they are inserted
    # as markup; everything derived from data is escaped.
    body = (
        f"<h1>{escape(TEXT['greeting'].format(agent=agent_name))}</h1>"
        f"<p>{TEXT['records_intro']}</p>"
        f'<p class="num">{escape(display_number(number_e164))}</p>'
        f"<h2>{escape(TEXT['what_it_does'])}</h2><ul>"
        f"<li>{TEXT['boundary_registered']}</li>"
        f"<li>{TEXT['boundary_second_sim']}</li>"
        f"<li>{TEXT['boundary_private']}</li>"
        f"<li>{TEXT['boundary_data']}</li>"
        "</ul>"
        f"<h2>{escape(TEXT['step_download'])}</h2>{download}"
        f'<p class="muted">{escape(hint)}</p>'
        f'<p class="muted">{escape(TEXT["other_version_prefix"] + other)}</p>'
        f"<h2>{escape(TEXT['step_play_protect'])}</h2>"
        f"<p>{escape(TEXT['play_protect_body'])}</p>"
        f"<h2>{escape(TEXT['step_code'])}</h2>"
        f'<p class="code">{escape(code)}</p>'
        f'<p><a href="{escape(deep_link)}">'
        f"{escape(TEXT['deep_link'])}</a></p>"
        f'<p class="muted">{escape(TEXT["stuck"])}</p>'
    )
    return _page(TEXT["page_title"], body)


def render_unavailable() -> str:
    """One page for an unknown, used, revoked or expired code.

    Deliberately identical in all four cases: the next action is the same, and
    the difference is only useful to somebody working through codes.
    """
    body = (
        f"<h1>{escape(TEXT['unavailable_title'])}</h1>"
        f"<p>{escape(TEXT['unavailable_body'])}</p>"
        f"<p>{escape(TEXT['unavailable_action'])}</p>"
    )
    return _page("BonviCall", body)


def render_apk_missing() -> str:
    """A live code but no published build yet. A dead button is worse."""
    body = (
        f"<h1>{escape(TEXT['apk_missing_title'])}</h1>"
        f"<p>{escape(TEXT['apk_missing_body'])}</p>"
        f"<p>{escape(TEXT['apk_missing_action'])}</p>"
    )
    return _page("BonviCall", body)
