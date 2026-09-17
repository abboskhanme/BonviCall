"""Scoring value objects — the names the rubric's output is spoken in.

Nothing here is a database column. ``ScoreBlock`` and ``RedFlagType`` are the
keys inside the ``blocks`` and ``red_flags`` JSONB documents, which is why they
are not in ``core/enums.py``: that file is the catalogue of PostgreSQL enum
types (CONVENTIONS.md §10), and a JSONB key is not one. ``Sentiment`` **did**
become a column and therefore moved — use ``core.enums.CallSentiment``.

The labels stay out of here on purpose. BonviZvonki carried ``BLOCK_LABEL_UZ``
and ``RED_FLAG_LABEL_UZ`` beside these enums; in BonviCall the panel's
``uz.json`` owns every string a person reads (CONVENTIONS.md §14).

SPEC-ANALYTICS §1.4. Task 7 merges the pipeline's stage outcomes into this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.modules.analysis.rubric_default import DEFAULT_RUBRIC


class ScoreBlock(StrEnum):
    """The four blocks of the rubric, as they appear in ``call_scores.blocks``."""

    SCRIPT = "script"  # A - script and structure
    COMMUNICATION = "communication"  # B - conduct
    RESOLUTION = "resolution"  # C - resolving the problem
    SALES_SKILL = "sales_skill"  # D - selling


#: Block maxima are **derived from the rubric**, never written out by hand.
#
# These values were once typed a second time and the two copies diverged:
# ``sales_skill`` was 15 in the code and 25 in the rubric. The analytics cut
# then drew 25/15 = 167 % and the bar left the chart, in front of a manager.
# One source, or none.
BLOCK_MAX: dict[ScoreBlock, int] = {
    ScoreBlock(block["key"]): int(block["max"]) for block in DEFAULT_RUBRIC["blocks"]
}


class RedFlagType(StrEnum):
    """Serious breaches. Each one subtracts, and one of them zeroes the score."""

    PROFANITY = "profanity"  # abuse or swearing -> score 0
    SHOUTING = "shouting"  # -20
    UNREALISTIC_PROMISE = "unrealistic_promise"  # -15
    BADMOUTHING = "badmouthing"  # the company or a colleague -> -15
    OFF_POLICY_DEAL = "off_policy_deal"  # a private deal outside the price list -> -25
    IGNORED_COMPLAINT = "ignored_complaint"  # -10


#: Mirrors the rubric's ``red_flags`` table. The **validator reads the rubric**,
#: not this dict — this exists for code that needs the number without loading
#: the rubric, and ``tests/test_scoring.py`` asserts the two agree.
RED_FLAG_PENALTY: dict[RedFlagType, int] = {
    RedFlagType.PROFANITY: -100,  # in practice: the overall score becomes 0
    RedFlagType.SHOUTING: -20,
    RedFlagType.UNREALISTIC_PROMISE: -15,
    RedFlagType.BADMOUTHING: -15,
    RedFlagType.OFF_POLICY_DEAL: -25,
    RedFlagType.IGNORED_COMPLAINT: -10,
}


@dataclass(slots=True)
class ScoreSummary:
    """One call's final score, as the panel reads it."""

    overall: int
    blocks: dict[str, int]
    red_flag_count: int
    confidence_pct: int
    needs_review: bool

    @property
    def grade(self) -> str:
        """The score as a band. The panel colours from this, never from the number."""
        if self.overall >= 85:
            return "excellent"
        if self.overall >= 70:
            return "good"
        if self.overall >= 55:
            return "average"
        return "poor"
