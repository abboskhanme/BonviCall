"""The three entry points, and the prefix each one answers on.

Three surfaces, three audiences, three lifecycles — they never share a router
and never share an auth dependency (SPEC §4):

* ``device``  the Android app, which **cannot be force-updated**. Versioned in
  the path, additive-only inside a major version, frozen contract.
* ``panel``   the web panel. Ships in lockstep with the server.
* ``service`` machine export and the callback receiver (UC-29). Versioned,
  additive-only, because BonviZvonki is wired to it in release 2.

**Naming note, because the two source documents disagree.** SPEC §4 calls the
mobile surface ``/api/mobile/v1``; CONVENTIONS.md §4 rule 1 calls it
``/api/device/v1`` and the committed contract artefact is
``contract/openapi-device-v1.json``. "device" is used here, because the
contract file name, the router package and the path then say the same word, and
one of the three had to give. Recorded in ``docs/ASSUMPTIONS.md``.
"""

from __future__ import annotations

#: The Android surface (N34's version gate applies to every route under it).
DEVICE_API_PREFIX = "/api/device/v1"

#: The panel surface. Unversioned in the path by SPEC §4: the panel is
#: deployed with the server, so there is never an old panel to keep serving.
PANEL_API_PREFIX = "/api/v1"

#: The machine surface. Versioned because its consumer is another product.
SERVICE_API_PREFIX = "/api/service/v1"

__all__ = ["DEVICE_API_PREFIX", "PANEL_API_PREFIX", "SERVICE_API_PREFIX"]
