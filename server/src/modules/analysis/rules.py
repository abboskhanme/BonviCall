"""Pure analysis rules — no session, no framework, no imports from ``src`` (§2).

``needs_review`` is the only source of the managers' review queue. The flag is
never set by accident: there are four triggers, each one records a machine
``code`` and its ``params``, and the panel's ``uz.json`` renders the sentence.
A manager opening the queue has to see why this call is there.

**Why a code and not a sentence.** BonviZvonki wrote a formatted Uzbek string
into ``review_reasons`` and the column then held display copy that no
translation, no wording change and no test could reach (SPEC-ANALYTICS §1.6).
Here the column holds ``[{"code": ..., "params": {...}}]`` and the words live in
one file the panel owns.

The codes, and the params each one always carries — the panel needs one string
per code and nothing else:

===================== ==================================================
``low_confidence``      ``confidence_pct``, ``threshold``
``low_transcript_quality`` ``quality``
``short_transcript``    ``words``, ``min_words``
``sparse_transcript``   ``words``, ``duration_sec``
``red_flag``            ``types`` (sorted, de-duplicated)
``na_over_budget``      — (no params)
===================== ==================================================

Each code carries the SAME params every time. One code with two different param
shapes is a blank line in the panel the day the other branch fires.

The thresholds live in one place because they are calibration values and will
move once there is enough scored data to calibrate against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# -- Thresholds ------------------------------------------------------------

#: Below this the model doubts its own score and a person looks at it.
#: An integer percent, not a 0..1 float: ``call_scores.confidence_pct`` is a
#: SMALLINT and the same number is compared in SQL and in TypeScript (§2.2).
MIN_CONFIDENCE = 70

#: Fewer words than this and the transcript is incomplete (the ASR dropped
#: speech, or the call was very short). The score cannot be trusted.
MIN_WORDS = 60

#: Word density in a long call: below this many words per second most of the
#: text is missing. Only applied past ``DENSITY_MIN_DURATION_SEC``.
MIN_WORDS_PER_SEC = 0.5
DENSITY_MIN_DURATION_SEC = 120


#: Service tokens in a transcript: ``[04:12]`` and ``SPEAKER_1:``.
#
# WHY THEY ARE NOT COUNTED. The threshold (``MIN_WORDS``) is about real SPOKEN
# words, but ``str.split()`` counts the service tokens too: in a 17-line
# transcript that is 34 fake "words", so a short conversation with 60 real words
# looks like 94 and the rule STOPS FIRING.
#
# It was a silent bug, and it silenced exactly the shortest — that is, the most
# suspect — conversations.
_TIMESTAMP = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")
_SPEAKER = re.compile(r"(?m)^\s*[A-Za-zА-Яа-яЎўҚқҒғҲҳ_0-9 .'-]{1,32}:\s")


def count_words(transcript_text: str | None) -> int:
    """Real words in the transcript, service tokens removed.

    The order matters: the timestamp goes first, because a line reads
    ``[00:02] Sotuvchi: ...`` and the speaker pattern is anchored to the start
    of the line.

    Stored on ``call_transcripts.word_count`` so the review rule and the panel
    agree on one number rather than each computing its own.
    """
    text = _TIMESTAMP.sub(" ", transcript_text or "")
    text = _SPEAKER.sub(" ", text)
    return len(text.split())


class ReviewReason:
    """The closed set of codes ``review_reasons`` may contain."""

    LOW_CONFIDENCE = "low_confidence"
    LOW_TRANSCRIPT_QUALITY = "low_transcript_quality"
    SHORT_TRANSCRIPT = "short_transcript"
    SPARSE_TRANSCRIPT = "sparse_transcript"
    RED_FLAG = "red_flag"
    NA_OVER_BUDGET = "na_over_budget"


#: For the panel's test: every code has a string in ``uz.json``, and nothing in
#: ``uz.json`` is a code this file no longer emits.
REVIEW_REASON_CODES: frozenset[str] = frozenset(
    {
        ReviewReason.LOW_CONFIDENCE,
        ReviewReason.LOW_TRANSCRIPT_QUALITY,
        ReviewReason.SHORT_TRANSCRIPT,
        ReviewReason.SPARSE_TRANSCRIPT,
        ReviewReason.RED_FLAG,
        ReviewReason.NA_OVER_BUDGET,
    }
)


@dataclass(slots=True)
class ReviewDecision:
    needs_review: bool
    reasons: list[dict[str, Any]] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [r["code"] for r in self.reasons]


def decide(
    *,
    confidence_pct: int,
    transcript_quality: str,
    transcript_text: str,
    duration_sec: int,
    red_flag_types: list[str],
    ai_score: int,
    na_over_budget: bool = False,
) -> ReviewDecision:
    """Run the rules in order.

    ``transcript_quality`` is a plain string and not ``core.enums``'
    ``TranscriptQuality``: this module may not import from ``src``, and
    ``TranscriptQuality`` is a ``StrEnum``, so the caller may pass either.

    ``ai_score`` is not read by any rule in phase 1. It stays in the signature
    on purpose (SPEC-ANALYTICS §1.4): it is the single input the client-survey
    gap rule needs, that rule returns in phase 3 with the surveys tables, and
    ``score.py``'s call site is written against this signature.
    """
    reasons: list[dict[str, Any]] = []

    # 1. Low confidence — the model itself is unsure
    if confidence_pct < MIN_CONFIDENCE:
        reasons.append(
            {
                "code": ReviewReason.LOW_CONFIDENCE,
                "params": {
                    "confidence_pct": confidence_pct,
                    "threshold": MIN_CONFIDENCE,
                },
            }
        )
    elif transcript_quality == "low":
        # Separate code rather than a second shape of `low_confidence`: the
        # panel renders one sentence per code, and a code whose params change
        # between branches renders as a blank the day the other branch fires.
        reasons.append(
            {
                "code": ReviewReason.LOW_TRANSCRIPT_QUALITY,
                "params": {"quality": transcript_quality},
            }
        )

    # 2. An unusually short transcript — the ASR may have lost speech
    words = count_words(transcript_text)
    if words < MIN_WORDS:
        reasons.append(
            {
                "code": ReviewReason.SHORT_TRANSCRIPT,
                "params": {"words": words, "min_words": MIN_WORDS},
            }
        )
    elif (
        duration_sec >= DENSITY_MIN_DURATION_SEC
        and words < duration_sec * MIN_WORDS_PER_SEC
    ):
        reasons.append(
            {
                "code": ReviewReason.SPARSE_TRANSCRIPT,
                "params": {"words": words, "duration_sec": duration_sec},
            }
        )

    # 3. Too many criteria marked "does not apply" in a long conversation. The
    #    score was accepted (the attempts ran out), but the employee may have
    #    skipped the stages and the model may have read that as "not required" —
    #    a PERSON decides.
    if na_over_budget:
        reasons.append({"code": ReviewReason.NA_OVER_BUDGET, "params": {}})

    # 4. A red flag is a serious accusation and a person must confirm it
    if red_flag_types:
        reasons.append(
            {
                "code": ReviewReason.RED_FLAG,
                "params": {"types": sorted(set(red_flag_types))},
            }
        )

    return ReviewDecision(needs_review=bool(reasons), reasons=reasons)
