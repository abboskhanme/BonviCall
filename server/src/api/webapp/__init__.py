"""The customer-facing Telegram Mini App surface — **NOT MOUNTED**.

═══ READ THIS BEFORE WIRING IT ═════════════════════════════════════════════
``main.py`` includes six routers and this is not one of them. That is
deliberate, and it is not an oversight to be tidied up:

* Every route here is **public and unauthenticated**. What stands in for a
  login is Telegram's HMAC over ``initData``, and that HMAC needs a bot token.
* **This deployment has no bot token and none is being asked for.**
  ``webapp.configured_bot_token()`` returns ``None``, so every request would
  answer 503 ``bot_not_configured`` — which is the correct refusal (an empty
  token would make the HMAC key derivable and any forgery would verify) but is
  not a surface worth exposing to the internet to say it.
* Nothing can post the deep link that brings a customer here, because
  ``modules/surveys/transport.py`` delivers nothing. A mounted door that
  nobody can be given the key to is attack surface and no more.

The handler is ported in full, with its verification, and it has tests
(``modules/surveys/tests/test_webapp_initdata.py``,
``test_webapp_router.py``) that mount this router on a throwaway app. So the
code is exercised; it just is not served.

**To turn it on**, in this order:
1. Return a real secret from ``webapp.configured_bot_token()``, sourced from
   ``core/config.py`` — never from ``app_settings``, which every manager can
   read.
2. Add ``("POST", "/api/webapp/surveys/open")`` and ``.../submit`` to
   ``PUBLIC_ROUTES`` in ``core/permissions.py``, or T20's RBAC harness will
   fail the build for two unprotected endpoints — which is exactly what that
   harness is for.
3. ``app.include_router(webapp.router)`` in ``main.py``.
4. Implement a real ``SurveyTransport``, or nothing will ever hand a customer
   the link.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.webapp import surveys

#: Its own prefix, not ``/api/v1``: this is a different audience with a
#: different auth mechanism, and §4's rule is that three surfaces never share a
#: router or an auth dependency. A fourth one does not get to either.
WEBAPP_API_PREFIX = "/api/webapp"

router = APIRouter(prefix=WEBAPP_API_PREFIX)
router.include_router(surveys.router)

__all__ = ["WEBAPP_API_PREFIX", "router"]
