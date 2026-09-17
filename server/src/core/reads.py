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
    # The activity report (ported from BonviZvonki ``modules/analytics``): who
    # called whom, how many went unanswered, which customers were never reached
    # and how long a callback took. It is one grouped aggregate per cut over
    # ``calls`` joined to ``agents``, plus a LATERAL for "the first contact
    # after this customer's last missed attempt" — assembling any of that from
    # per-row service calls would be a query per employee per day, and the
    # report would be rewritten as raw SQL by the first person who timed it.
    # Owns no table: everything it reports is derived.
    "activity": frozenset(
        {
            "calls.CallModel",
            "agents.AgentModel",
        }
    ),
    # The customer directory (ported from BonviZvonki ``modules/clients``):
    # one phone number, every conversation held with it, and the name the
    # uploaded phonebooks give it. It owns no table and never will —
    # everything it reports is derived, which is the same decision §10 makes
    # about the gap report and the capture-rate delta.
    #
    # ``contacts.ClientContactModel`` is read rather than asked for through
    # ``ContactService`` because the name has to be resolved INSIDE the grouped
    # aggregate: it is a 1:1 LEFT JOIN on a unique ``phone_key``, and pulling
    # it out into a second query is what leaves BonviZvonki's list sorted by a
    # column it does not show. It is a column projection like every other read
    # here, and the arrow only points one way — ``contacts`` calls
    # ``ClientDirectory`` for its call counts, never the reverse.
    #
    # ``analysis.CallScoreModel`` for the same reason ``analytics`` reads it:
    # the average score per customer is an aggregate over every score in the
    # window, and assembling that from per-row service calls is the case this
    # exception exists for.
    "clients": frozenset(
        {
            "calls.CallModel",
            "agents.AgentModel",
            "analysis.CallScoreModel",
            "contacts.ClientContactModel",
        }
    ),
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
    # The analytics dashboard (SPEC-ANALYTICS phase 2): six aggregates over the
    # calls this product has already scored — KPI overview, trend, agent
    # ranking, rubric blocks, breaches, score histogram. It owns no table and
    # never will: everything it reports is recomputed from the two it reads,
    # which is the same decision §10 makes about the gap report.
    #
    # ``analysis.CallScoreModel`` rather than a call into ``AnalysisService``:
    # the answer is four GROUP BYs over every score in a window, and assembling
    # that from per-row service calls is the case this exception exists for —
    # fine over fifty scored calls, fatal over fifty thousand.
    "analytics": frozenset(
        {
            "calls.CallModel",
            "agents.AgentModel",
            "analysis.CallScoreModel",
        }
    ),
}

__all__ = ["CROSS_MODULE_READS"]
