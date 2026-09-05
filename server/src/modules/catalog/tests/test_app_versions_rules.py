"""The APK reader, against real builds (T58, N33).

Every other test in this module uses a synthetic zip, which proves the *shape*
the parser expects and nothing about whether that shape is what Gradle emits.
This file reads the actual output of ``./gradlew assembleDebug`` and skips when
it has not been built — a skipped test that says why is better than a green one
that only ever saw a fixture I wrote to match my own parser.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.modules.catalog.rules import inspect_apk, normalise_fingerprint

APK_DIR = Path(__file__).resolve().parents[4] / "android/app/build/outputs/apk"
DEBUG_APK = APK_DIR / "modern34/debug/app-modern34-debug.apk"
UNSIGNED_APK = APK_DIR / "modern34/release/app-modern34-release-unsigned.apk"


@pytest.mark.skipif(not DEBUG_APK.is_file(), reason="APK not built; run ./gradlew")
def test_a_real_debug_build_yields_its_signing_certificate() -> None:
    """The whole point: read the signer out of a file Gradle actually produced.

    Cross-checked once by hand against ``cryptography``: the bytes this
    extracts load as an X.509 certificate with subject ``CN=Android Debug`` and
    the same SHA-256. That check is not repeated here because it would add a
    dependency to the suite for a one-off verification.
    """
    inspection = inspect_apk(DEBUG_APK.read_bytes())

    assert inspection.is_apk
    assert inspection.is_signed, inspection.reason
    assert len(inspection.signer_sha256) == 64
    assert int(inspection.signer_sha256, 16) >= 0  # it is hex
    assert inspection.sha256 == hashlib.sha256(DEBUG_APK.read_bytes()).hexdigest()
    assert inspection.size_bytes == DEBUG_APK.stat().st_size


@pytest.mark.skipif(not UNSIGNED_APK.is_file(), reason="APK not built; run ./gradlew")
def test_a_real_unsigned_release_is_recognised_as_unsigned() -> None:
    """And the negative, from a real file rather than a doctored one.

    This project's builds have **no** ``META-INF/*.RSA`` at all — Gradle signs
    v2/v3 only at this minSdk — which is why the parser reads the signing block
    and does not fall back to the legacy JAR signature. A fallback would find
    nothing here and report every build as unsigned.
    """
    inspection = inspect_apk(UNSIGNED_APK.read_bytes())

    assert inspection.is_apk
    assert not inspection.is_signed
    assert inspection.reason == "no_v2_signature"


def test_garbage_is_an_answer_and_not_an_exception() -> None:
    """A bad upload is a 422 with a reason, never a 500."""
    assert inspect_apk(b"").reason == "not_a_zip"
    assert inspect_apk(b"PK\x03\x04 truncated").reason == "not_a_zip"


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("AA:BB:CC", "aabbcc"),
        ("aabbcc", "aabbcc"),
        ("AA BB CC", "aabbcc"),
        ("", None),
        (None, None),
    ],
)
def test_a_fingerprint_is_compared_however_it_was_typed(written, expected) -> None:
    """``keytool`` prints colons, ``apksigner`` does not, and a person types one."""
    assert normalise_fingerprint(written) == expected
