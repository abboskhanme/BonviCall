"""Every storage root the app writes to must survive a container restart.

``/data/releases`` had no volume. The row survived in Postgres, the bytes did
not, and the install page served a 404 to every salesperson from the next
``compose up`` onward — silently, because the upload had returned 201 and the
panel listed the build as published.

This is the project's recurring failure shape once more (``STATUS.md``: *a
finished component with no caller*), in the one place a Python test does not
normally look. So the compose file is mounted read-only into the backend
container and asserted here rather than reviewed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.config import Settings

COMPOSE = Path("/compose/docker-compose.yml")


def _backend_service() -> dict:
    assert COMPOSE.is_file(), (
        f"{COMPOSE} is not mounted. It is mounted read-only by docker-compose.yml "
        "itself so this test can run; if that mount was removed, restore it "
        "rather than deleting the test."
    )
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["backend"]


def _mount_targets(service: dict) -> set[str]:
    targets = set()
    for entry in service.get("volumes", []):
        # "source:target" or "source:target:ro"
        parts = str(entry).split(":")
        if len(parts) >= 2:
            targets.add(parts[1])
    return targets


def _deployed_path(setting_name: str) -> str:
    """The DEPLOYED default, not the running one.

    ``conftest`` points the audio root at a tmp directory for the suite, so
    asking `get_settings()` would test the fixture instead of the deployment
    and pass or fail for the wrong reason.
    """
    return str(Settings.model_fields[setting_name].default)


@pytest.mark.parametrize(
    "setting_name",
    ["audio_storage_path", "release_storage_path"],
)
def test_every_storage_root_is_on_a_volume(setting_name: str) -> None:
    root = _deployed_path(setting_name)
    targets = _mount_targets(_backend_service())

    covered = any(root == t or root.startswith(t.rstrip("/") + "/") for t in targets)
    assert covered, (
        f"settings.{setting_name} = {root} is not covered by any volume on the "
        f"backend service (mounts: {sorted(targets)}). Anything written there "
        "lives in the container's writable layer and is lost on the next "
        "`compose up`."
    )


def test_the_release_root_is_not_inside_the_audio_root() -> None:
    """A retention sweep must never be able to reach the APK.

    ``core/storage.py`` states this as the reason the two stores are separate;
    nothing checked that the paths actually stayed apart.
    """
    audio = _deployed_path("audio_storage_path").rstrip("/") + "/"
    release = _deployed_path("release_storage_path").rstrip("/") + "/"
    assert not release.startswith(audio)
    assert not audio.startswith(release)
