"""Phone normalisation against the shared vectors (CONVENTIONS.md §7).

These vectors are read by the Android test suite too. A format that behaves
differently on the two sides is a silent join failure in release 2, so the file
is shared rather than the expectations being written twice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.phone import (
    PHONE_KEY_DIGITS,
    is_extension,
    phone_key,
    to_e164,
)

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "contract" / "phone-vectors.json").read_text()
)


def test_key_digits_matches_the_contract() -> None:
    """The shared file and the code must agree on the length of the key."""
    assert PHONE_KEY_DIGITS == VECTORS["phone_key_digits"]


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=lambda v: repr(v["raw"]))
def test_phone_key(vector: dict) -> None:
    assert phone_key(vector["raw"]) == vector["key"], vector["note"]


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=lambda v: repr(v["raw"]))
def test_to_e164(vector: dict) -> None:
    assert to_e164(vector["raw"]) == vector["e164"], vector["note"]


@pytest.mark.parametrize("raw", VECTORS["extensions"])
def test_extensions_are_extensions(raw: str) -> None:
    assert is_extension(raw) is True


@pytest.mark.parametrize("raw", VECTORS["not_extensions"])
def test_real_numbers_are_not_extensions(raw: str) -> None:
    assert is_extension(raw) is False


@pytest.mark.parametrize("raw", VECTORS["extensions"])
def test_an_extension_never_gets_a_key(raw: str) -> None:
    """The BonviZvonki defect, pinned: a short number matched everyone's tail."""
    assert phone_key(raw) is None
