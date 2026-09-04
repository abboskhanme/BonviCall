"""Scheduled work owned by ``commands`` (T151, UC-16)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.commands.service import CommandService


async def command_timeout(session: AsyncSession) -> int:
    """Fail unacknowledged commands, expire stale ones (SPEC §4.6).

    Idempotent by construction: the query only matches commands still in
    ``pending`` or ``sent``, so a second run has nothing left to change.
    Runs every ten seconds, because UC-16's whole promise is that a person
    watching the panel sees the outcome quickly — including the outcome
    "it did not work".
    """
    return await CommandService(session).expire_stale()
