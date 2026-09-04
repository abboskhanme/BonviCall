"""Keyset (cursor) pagination for panel lists (SPEC §4.0).

The guarantee, stated precisely because "stable" is otherwise unfalsifiable:
**no row that existed when paging started is skipped or returned twice.** Rows
inserted during the pass may or may not appear; they never displace others.
That is exactly what UC-19 asks for and exactly what keyset gives — an ``OFFSET``
does not, because a call arriving mid-pass shifts every later page by one.

**Every sort must include ``id``.** Two calls received in the same millisecond
have equal sort values, and without a tiebreak the pass can loop or skip.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from src.core.errors import BadRequestError, ErrorCode

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: UC-19 renders a thousand rows in one page, so /calls raises the ceiling.
MAX_LIMIT_CALLS = 1000


@dataclass(frozen=True)
class Cursor:
    """The opaque marker: the sort value plus the id that breaks its ties."""

    sort_value: Any
    row_id: uuid.UUID

    def encode(self) -> str:
        payload = {"k": [_to_json(self.sort_value), str(self.row_id)]}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def decode(value: str) -> Cursor:
        try:
            padded = value + "=" * (-len(value) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            sort_value, row_id = payload["k"]
            return Cursor(sort_value=sort_value, row_id=uuid.UUID(row_id))
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            # A tampered or truncated cursor is a client bug, not a server one.
            # 400 rather than 500, and never a silent restart from page one:
            # silently restarting is how an export ends up with duplicate rows.
            raise BadRequestError(
                ErrorCode.BAD_REQUEST, detail={"field": "cursor"}
            ) from exc


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page plus the marker for the next one."""

    items: list[T]
    next_cursor: str | None
    has_more: bool
    total: int | None = None


def clamp_limit(limit: int | None, maximum: int = MAX_LIMIT) -> int:
    """A caller-supplied limit, kept inside the range the indexes are sized for."""
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        raise BadRequestError(ErrorCode.BAD_REQUEST, detail={"field": "limit"})
    return min(limit, maximum)


def coerce_sort_value(sort_column: InstrumentedAttribute, value: Any) -> Any:
    """Turn a decoded cursor value back into the column's own Python type.

    A cursor travels as JSON, so a ``timestamptz`` arrives as an ISO string and
    PostgreSQL refuses to compare the two — "operator does not exist:
    timestamp with time zone < character varying", which is a 500 on a request
    the client did nothing wrong in. The column knows its own type, so ask it.
    """
    if value is None:
        return None
    try:
        python_type = sort_column.type.python_type
    except NotImplementedError:  # a type with no Python analogue; pass it through
        return value
    if python_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    if python_type is date and isinstance(value, str):
        return date.fromisoformat(value)
    if python_type is int and isinstance(value, str):
        return int(value)
    return value


def apply_keyset(
    statement: Select,
    sort_column: InstrumentedAttribute,
    id_column: InstrumentedAttribute,
    cursor: Cursor | None,
    descending: bool = True,
) -> Select:
    """Order by ``(sort_column, id)`` and seek past ``cursor``."""
    if cursor is not None:
        cursor = Cursor(
            sort_value=coerce_sort_value(sort_column, cursor.sort_value),
            row_id=cursor.row_id,
        )
    if descending:
        statement = statement.order_by(sort_column.desc(), id_column.desc())
        if cursor is not None:
            statement = statement.where(
                or_(
                    sort_column < cursor.sort_value,
                    and_(sort_column == cursor.sort_value, id_column < cursor.row_id),
                )
            )
    else:
        statement = statement.order_by(sort_column.asc(), id_column.asc())
        if cursor is not None:
            statement = statement.where(
                or_(
                    sort_column > cursor.sort_value,
                    and_(sort_column == cursor.sort_value, id_column > cursor.row_id),
                )
            )
    return statement


def _to_json(value: Any) -> Any:
    """Cursor values travel as JSON, so a datetime becomes ISO-8601."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_LIMIT_CALLS",
    "Cursor",
    "Page",
    "apply_keyset",
    "clamp_limit",
]
