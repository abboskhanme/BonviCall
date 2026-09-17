"""Every function in ``analysis/rules.py`` (CONVENTIONS.md §13).

One case per trigger of the review queue, plus the word counter the short
transcript rule stands on. No database on purpose: these are the rules a manager
sees the consequences of, and a rule that important should not be reachable only
through fixtures.

Ported from BonviZvonki's ``scoring/tests/test_review_rules.py``, adapted to
assert on ``code`` and ``params`` rather than on an Uzbek sentence, and with the
client-survey gap cases dropped (phase 3, §1.4).
"""

from __future__ import annotations

from src.modules.analysis.rules import (
    DENSITY_MIN_DURATION_SEC,
    MIN_CONFIDENCE,
    MIN_WORDS,
    REVIEW_REASON_CODES,
    ReviewReason,
    count_words,
    decide,
)
from src.modules.analysis.tests.stubs import SAMPLE_TRANSCRIPT, SHORT_TRANSCRIPT

LONG_TEXT = " ".join(["so'z"] * 200)


def _decide(**overrides):
    base = dict(
        confidence_pct=95,
        transcript_quality="high",
        transcript_text=LONG_TEXT,
        duration_sec=180,
        red_flag_types=[],
        ai_score=78,
    )
    return decide(**(base | overrides))


def _reason(decision, code: str) -> dict:
    return next(r for r in decision.reasons if r["code"] == code)


# -- count_words -----------------------------------------------------------


def test_the_word_count_ignores_timestamps_and_speaker_labels() -> None:
    """WHY THEY ARE NOT COUNTED — this was a silent bug.

    ``MIN_WORDS`` is about real spoken words, but ``str.split()`` counts the
    service tokens too: in a 17-line transcript that is 34 fake "words", so a
    60-word conversation looks like 94 and the rule STOPS FIRING. It silenced
    exactly the shortest, most suspect calls.
    """
    text = "[00:02] Sotuvchi: Assalomu alaykum\n[00:06] Mijoz: Ha eshitaman"

    assert count_words(text) == 4
    assert count_words(text) < len(text.split())


def test_the_word_count_handles_no_transcript() -> None:
    assert count_words(None) == 0
    assert count_words("") == 0


def test_the_sample_transcript_is_above_the_short_threshold() -> None:
    """A guard on the fixture: the sample must not trip the shortness rule."""
    assert count_words(SAMPLE_TRANSCRIPT) > MIN_WORDS


def test_a_two_line_transcript_is_below_it() -> None:
    assert count_words(SHORT_TRANSCRIPT) < MIN_WORDS


# -- decide ----------------------------------------------------------------


def test_a_clean_call_is_not_flagged() -> None:
    decision = _decide()

    assert decision.needs_review is False
    assert decision.reasons == []


def test_low_confidence_triggers() -> None:
    decision = _decide(confidence_pct=52)

    assert decision.needs_review is True
    assert decision.codes == [ReviewReason.LOW_CONFIDENCE]
    assert _reason(decision, ReviewReason.LOW_CONFIDENCE)["params"] == {
        "confidence_pct": 52,
        "threshold": MIN_CONFIDENCE,
    }


def test_confidence_exactly_at_the_threshold_does_not_trigger() -> None:
    """The boundary is stated once, here, rather than argued about later."""
    assert _decide(confidence_pct=MIN_CONFIDENCE).needs_review is False
    assert _decide(confidence_pct=MIN_CONFIDENCE - 1).needs_review is True


def test_low_transcript_quality_triggers_its_own_code() -> None:
    """A separate code, not a second shape of ``low_confidence``.

    The panel renders one sentence per code; a code whose params change between
    branches renders as a blank the day the other branch fires.
    """
    decision = _decide(transcript_quality="low")

    assert decision.codes == [ReviewReason.LOW_TRANSCRIPT_QUALITY]
    assert _reason(decision, ReviewReason.LOW_TRANSCRIPT_QUALITY)["params"] == {
        "quality": "low"
    }


def test_low_confidence_wins_over_low_quality() -> None:
    """One reason for one cause: both firing would say the same thing twice."""
    decision = _decide(confidence_pct=40, transcript_quality="low")

    assert decision.codes == [ReviewReason.LOW_CONFIDENCE]


def test_a_short_transcript_triggers() -> None:
    decision = _decide(transcript_text="Assalomu alaykum. Noto'g'ri raqam.")

    assert ReviewReason.SHORT_TRANSCRIPT in decision.codes
    assert _reason(decision, ReviewReason.SHORT_TRANSCRIPT)["params"] == {
        "words": 4,
        "min_words": MIN_WORDS,
    }


def test_a_sparse_long_call_triggers() -> None:
    """100 words in a ten-minute conversation — most of the text is missing."""
    decision = _decide(transcript_text=" ".join(["so'z"] * 100), duration_sec=600)

    assert ReviewReason.SPARSE_TRANSCRIPT in decision.codes
    assert _reason(decision, ReviewReason.SPARSE_TRANSCRIPT)["params"] == {
        "words": 100,
        "duration_sec": 600,
    }


def test_density_is_not_applied_to_a_short_call() -> None:
    """Under two minutes the density rule would fire on ordinary speech."""
    decision = _decide(
        transcript_text=" ".join(["so'z"] * 61),
        duration_sec=DENSITY_MIN_DURATION_SEC - 1,
    )

    assert decision.needs_review is False


def test_a_red_flag_triggers_and_names_the_types() -> None:
    decision = _decide(red_flag_types=["shouting", "shouting", "badmouthing"])

    assert ReviewReason.RED_FLAG in decision.codes
    # Sorted and de-duplicated: the panel prints the list verbatim
    assert _reason(decision, ReviewReason.RED_FLAG)["params"] == {
        "types": ["badmouthing", "shouting"]
    }


def test_na_over_budget_triggers_with_no_params() -> None:
    decision = _decide(na_over_budget=True)

    assert decision.codes == [ReviewReason.NA_OVER_BUDGET]
    assert _reason(decision, ReviewReason.NA_OVER_BUDGET)["params"] == {}


def test_several_reasons_are_all_recorded() -> None:
    """The queue must show every reason, not the first one found."""
    decision = _decide(
        confidence_pct=40,
        transcript_text=SHORT_TRANSCRIPT,
        red_flag_types=["profanity"],
        na_over_budget=True,
    )

    assert set(decision.codes) == {
        ReviewReason.LOW_CONFIDENCE,
        ReviewReason.SHORT_TRANSCRIPT,
        ReviewReason.NA_OVER_BUDGET,
        ReviewReason.RED_FLAG,
    }


def test_every_emitted_code_is_in_the_declared_set() -> None:
    """``REVIEW_REASON_CODES`` is what the panel's ``uz.json`` is checked against.

    A code emitted but not declared is a reason that renders as a blank row in
    the review queue — the one screen whose whole job is saying why.
    """
    decision = _decide(
        confidence_pct=40,
        transcript_text=SHORT_TRANSCRIPT,
        red_flag_types=["profanity"],
        na_over_budget=True,
    )
    sparse = _decide(transcript_text=" ".join(["so'z"] * 100), duration_sec=600)
    quality = _decide(transcript_quality="low")

    emitted = set(decision.codes) | set(sparse.codes) | set(quality.codes)

    assert emitted == set(REVIEW_REASON_CODES)


def test_the_reasons_are_json_serialisable() -> None:
    """They land in a JSONB column; a dataclass or a set would fail on write."""
    import json

    decision = _decide(confidence_pct=40, red_flag_types=["shouting"])

    assert json.loads(json.dumps(decision.reasons)) == decision.reasons
