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


# --- The deployment file (docs/SECURITY-BACKLOG.md items 4 and 5) -----------
#
# `docker-compose.prod.yml` is the file nobody runs while developing, so
# nothing would notice a line going missing from it until the day it mattered.
# It is mounted read-only beside the development one and asserted here.

PROD_COMPOSE = Path("/compose/docker-compose.prod.yml")


def _prod() -> dict:
    assert PROD_COMPOSE.is_file(), (
        f"{PROD_COMPOSE} is not mounted. docker-compose.yml mounts it read-only "
        "so this test can run; restore that mount rather than deleting the test."
    )
    return yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))["services"]


def test_the_deployed_database_publishes_no_port() -> None:
    """On a laptop 5443 is convenient. On a server it is the database, offered
    to the internet with one password in front of it."""
    assert not _prod()["postgres"].get("ports"), (
        "docker-compose.prod.yml publishes a postgres port. The backend reaches "
        "it over the compose network and nothing else should reach it at all."
    )


@pytest.mark.parametrize("service_name", ["backend", "worker"])
def test_the_deployed_app_does_not_run_as_root(service_name: str) -> None:
    """A container escape from root is host root.

    ``server/Dockerfile`` creates uid 10001 and gives it ``/data``; this is the
    line that selects it, and it lives here rather than in the image because
    development keeps volumes that were created root-owned long before.
    """
    user = str(_prod()[service_name].get("user", ""))
    assert user.startswith("10001"), (
        f"{service_name} in docker-compose.prod.yml runs as {user or 'root'}. "
        "It must be `user: \"10001:10001\"` — the uid server/Dockerfile owns "
        "/data/audio and /data/releases with."
    )


@pytest.mark.parametrize("setting_name", ["audio_storage_path", "release_storage_path"])
def test_every_storage_root_is_on_a_volume_in_the_deployment_too(
    setting_name: str,
) -> None:
    """The same rule as above, on the file where losing the bytes is permanent.

    The backend writes audio and the worker only reads and deletes it, so the
    APK store is the backend's alone; both roots are checked against whichever
    service mounts them.
    """
    root = _deployed_path(setting_name)
    targets = _mount_targets(_prod()["backend"])
    assert any(root == t or root.startswith(t.rstrip("/") + "/") for t in targets), (
        f"settings.{setting_name} = {root} has no volume in "
        f"docker-compose.prod.yml (mounts: {sorted(targets)})."
    )


def test_the_deployed_backend_trusts_the_proxy_for_the_caller_address() -> None:
    """Without this the rate limits count the whole fleet as one caller.

    Behind Caddy ``request.client.host`` is Caddy. ``--proxy-headers`` is what
    makes Starlette resolve the forwarded address instead, and every per-IP
    limit in ``core/ratelimit.py`` depends on it — including the one that must
    not refuse the eleventh salesperson enrolling from the office Wi-Fi.
    """
    command = str(_prod()["backend"].get("command", ""))
    assert "--proxy-headers" in command


def test_the_deployed_backend_publishes_no_port_of_its_own() -> None:
    """Which is the entire reason ``--forwarded-allow-ips="*"`` is safe above.

    Trusting X-Forwarded-For from anything that can connect is only acceptable
    while the only thing that can connect is on the compose network. Publishing
    a port here would let any caller choose its own rate-limit bucket by
    sending a header, and the two lines are far enough apart in the file that
    nobody would connect them.
    """
    assert not _prod()["backend"].get("ports")
