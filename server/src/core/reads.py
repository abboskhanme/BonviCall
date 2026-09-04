"""Modules allowed to read another module's models (CONVENTIONS.md §2.1).

The base rule is that a module imports another module's **service**, never its
models. Two release-1 modules own no table and exist only to compute an answer
from other modules' data — ``gaps`` (UC-23) and ``exports`` (UC-29) — and
assembling those from per-row service calls would make the gap report, the
product's own smoke alarm for "a phone stopped producing audio", slow enough
that somebody later replaces it with a raw query. The rule would then be broken
by accident instead of on purpose.

So the exception is granted and fenced. It is **read-only**, it covers exactly
the models named below, and it only applies to a module with no ``models.py``.
The holders issue column projections and aggregates only — never
``select(CallModel)`` — so no foreign ORM entity is ever loaded and none can
escape past the service boundary.

**This exception does not cover single-row lookups.** ``auth`` reads one user
per login through a service round-trip, which is what the base rule is for.

``CallAudioModel`` is listed under ``audio`` and not ``calls``: §2.1's draft put
it in the wrong module, and the AST check compares against where the class
actually lives.

``tests/test_layering.py`` parses every ``modules/*/service.py`` and fails when
this file and the code disagree. The list cannot grow silently — it grows in a
diff, in one file, with a line in ``docs/ASSUMPTIONS.md``.
"""

from __future__ import annotations

#: Modules that own no table and may read other modules' models in aggregate
#: SELECTs. Read-only. Adding an entry needs a line in docs/ASSUMPTIONS.md;
#: a module that later gains a table loses the exception.
CROSS_MODULE_READS: dict[str, frozenset[str]] = {
    "gaps": frozenset(
        {
            "calls.CallModel",
            "audio.CallAudioModel",
            "devices.CallLogDeltaModel",
            "devices.DeviceHealthModel",
            "devices.DeviceModel",
            "installations.InstallationModel",
            "agents.AgentModel",
            "catalog.SupportedModelModel",
            # The regression threshold is a settings row, and reading one value
            # through a service would be a round-trip per report.
            "settings.AppSettingModel",
        }
    ),
    "exports": frozenset(
        {
            "calls.CallModel",
            "audio.CallAudioModel",
            "agents.AgentModel",
            "numbers.RegisteredNumberModel",
            "numbers.NumberAssignmentModel",
        }
    ),
}

__all__ = ["CROSS_MODULE_READS"]
