"""Small SQL text helpers shared by every module's query building.

One function so far, and it exists because forgetting it is silent: a search
for ``100%`` that is not escaped matches every row and looks like a working
search.
"""

from __future__ import annotations


def escape_like(value: str) -> str:
    """Escape ``ILIKE`` metacharacters so a literal ``%`` matches a ``%``.

    Adopted from the reference module's ``_ilike_ekranla``. Without it ``%``
    matches everything and ``_`` matches any single character, so a customer
    called "A_B" finds every three-letter name.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["escape_like"]
