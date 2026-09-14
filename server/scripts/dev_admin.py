"""A short operator login for a machine somebody is working on.

    make dev-admin            # admin / admin
    make dev-admin u=bonvi p=bonvi2026

Creates the account if it is missing and resets its password if it is not, so
it is the answer to "I cannot get into the panel" as well as to "give me a
short login".

═══ Why this is a script and not a setting ════════════════════════════════
``src/seed.py`` creates the first admin and **refuses** a password like this:
under ten characters, or one of ``INSECURE_PASSWORDS``. That refusal is right
and stays exactly as it is — it guards the account a deployment ships with.

This file is the other case: a laptop, a demonstration, a stack that is torn
down at the end of the day. It writes the hash directly rather than going
through ``UserService``, so the policy it is stepping around is stepped around
in **one** visible place rather than being loosened for everybody.

**It refuses to run in production.** Not a warning and not a flag: the whole
point of the password rule is the deployment, and a script that could be
pointed at one would eventually be.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Run as a file rather than as a module (`python scripts/dev_admin.py`), so the
# package root is not on the path the way `python -m src.seed` puts it there.
sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from src.core import database  # noqa: E402

# Every entry point imports the registry before touching a model (§10).
from src.core import models as _model_registry  # noqa: F401,E402
from src.core.config import get_settings  # noqa: E402
from src.core.enums import UserRole  # noqa: E402
from src.core.logging import configure_logging, get_logger  # noqa: E402
from src.core.security import hash_password  # noqa: E402
from src.modules.users.models import UserModel  # noqa: E402

log = get_logger(__name__)

DEFAULT_LOGIN = "admin"
DEFAULT_PASSWORD = "admin"


async def upsert_dev_admin(login: str, password: str) -> str:
    """Create or reset the account. Returns what happened, for the operator."""
    async with database.get_sessionmaker()() as session:
        user = await session.scalar(select(UserModel).where(UserModel.email == login))
        if user is None:
            session.add(
                UserModel(
                    email=login,
                    password_hash=hash_password(password),
                    full_name="Administrator",
                    role=UserRole.ADMIN,
                    # False on purpose: the point of this account is to get
                    # into the panel in one step, and a forced change on first
                    # login is the second step.
                    must_change_password=False,
                )
            )
            outcome = "created"
        else:
            user.password_hash = hash_password(password)
            user.role = UserRole.ADMIN
            user.is_active = True
            user.must_change_password = False
            outcome = "reset"
        await session.commit()
    return outcome


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)

    if settings.is_production:
        print("Refusing: ENVIRONMENT=prod. Use `make seed` and a real password.")
        return 1

    login = os.environ.get("DEV_ADMIN_LOGIN", DEFAULT_LOGIN).strip() or DEFAULT_LOGIN
    password = os.environ.get("DEV_ADMIN_PASSWORD", DEFAULT_PASSWORD) or DEFAULT_PASSWORD

    outcome = asyncio.run(upsert_dev_admin(login, password))
    # Printed, never logged: N26 keeps secrets out of log lines, and this one
    # belongs on the operator's terminal.
    print(f"{outcome}: login '{login}', password '{password}'  ·  panel http://localhost:5190")
    print("This account is for a development machine. Do not ship it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
