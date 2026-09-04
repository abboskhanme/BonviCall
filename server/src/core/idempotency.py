"""One idempotency helper, one shape (CONVENTIONS.md §5).

Every device write carries a client-generated UUID in the **body** — not a
header: it has to survive as a Room column across app restarts, and headers get
dropped by retry plumbing.

**The forbidden implementation is the natural one.** ``SELECT`` then ``INSERT if
missing`` double-inserts under exactly the retry storm this exists to survive:
two uploads of the same record race between the read and the write, both see
nothing, both insert. The only correct shape is to let the database decide::

    INSERT ... ON CONFLICT (<key>) DO NOTHING RETURNING id
    -- then SELECT, but only when nothing came back

The response is **always 200 with the same server id**, so a first write and a
replay are indistinguishable to the client (UC-12).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


async def upsert_once(
    session: AsyncSession,
    model: type[DeclarativeBase],
    key_column: str,
    values: dict[str, Any],
) -> tuple[uuid.UUID, bool]:
    """Insert ``values`` unless ``key_column`` is already taken.

    :returns: ``(id, created)`` — ``created`` is False when the row already
        existed, which is what lets the caller answer ``status: "unchanged"``
        without a second query.
    """
    table = model.__table__
    statement = (
        insert(table)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[key_column])
        .returning(table.c.id)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()
    if inserted is not None:
        return inserted, True

    existing = (
        await session.execute(
            select(table.c.id).where(table.c[key_column] == values[key_column])
        )
    ).scalar_one()
    return existing, False


__all__ = ["upsert_once"]
