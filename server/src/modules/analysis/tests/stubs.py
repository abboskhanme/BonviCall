"""Fixtures for tests that must run with no network, no key and no bill.

``build_payload`` produces a rubric-shaped answer whose arithmetic is CORRECT,
which is what lets a validator test assert on the numbers rather than on a
recorded blob. ``overall_override`` and ``invented_flag`` exist to break it
deliberately.

Task 7 adds the fake ASR and LLM clients here (SPEC-ANALYTICS §9.1); this file
holds only what the pure scoring tests need, and imports nothing from ``src``.
"""

from __future__ import annotations

import random
from typing import Any

# -- A sample transcript (mixed Uzbek/Russian, as the calls really are) -----
#
# Kept in the source language deliberately: it is test DATA standing in for what
# the ASR returns, and ``rules.count_words`` is measured against the service
# tokens in exactly this shape.

#: Joined rather than written as one block literal purely to keep the source
#: inside the line limit — the resulting string is byte-identical to the real
#: transcript shape, service tokens and all.
_SAMPLE_LINES = (
    "[00:02] Sotuvchi: Assalomu alaykum, men Sardor, Bonvi kompaniyasidan "
    "qo'ng'iroq qilyapman.",
    "[00:06] Mijoz: Va alaykum assalom, ha eshitaman.",
    "[00:09] Sotuvchi: Ozgina vaqtingizni olsam maylimi? Do'koningizda hozir "
    "qaysi mahsulotlarimiz bor edi?",
    "[00:15] Mijoz: X-200 dan bor, lekin tugab qoldi. Y-50 umuman yo'q.",
    "[00:22] Sotuvchi: Tushunarli. Y-50 hozir aksiyada, 50 tadan olsangiz narxi "
    "ancha qulay bo'ladi.",
    "[00:31] Mijoz: А сколько будет стоить? Narxi qanday?",
    "[00:35] Sotuvchi: Bir dona 42 ming so'm, 50 tadan olsangiz 39 mingdan.",
    "[00:44] Mijoz: Qimmatroq ekan, o'ylab ko'ray.",
    "[00:47] Sotuvchi: Albatta. Aksiya juma kuni tugaydi, shuning uchun "
    "bugun-erta hal qilsangiz yaxshi bo'lardi.",
    "[00:58] Mijoz: Mayli, ertaga aytaman.",
    "[01:02] Sotuvchi: Yaxshi, men payshanba kuni soat 10 da qayta qo'ng'iroq "
    "qilaman. Xaridingiz uchun rahmat!",
    "[01:09] Mijoz: Xayr, ko'rishguncha.",
)

SAMPLE_TRANSCRIPT = "\n".join(_SAMPLE_LINES)

SHORT_TRANSCRIPT = "[00:01] Sotuvchi: Assalomu alaykum. [00:03] Mijoz: Noto'g'ri raqam."


def build_payload(
    rubric_blocks: list[dict[str, Any]],
    rubric_red_flags: list[dict[str, Any]],
    *,
    ratio: float = 0.8,
    red_flags: tuple[str, ...] = (),
    confidence: float = 0.92,
    quality: str = "high",
    seed: int = 0,
    overall_override: int | None = None,
    invented_flag: str | None = None,
) -> dict[str, Any]:
    """A rubric-shaped answer whose arithmetic is CORRECT.

    Seeded, so a failure is reproducible from the test name alone.
    """
    rng = random.Random(seed)
    blocks: dict[str, Any] = {}
    total = 0

    for block in rubric_blocks:
        criteria = []
        block_total = 0
        for criterion in block.get("criteria", []):
            points = int(criterion.get("points", 0))
            noise = rng.uniform(-0.15, 0.15)
            score = max(0, min(points, round(points * (ratio + noise))))
            block_total += score
            criteria.append(
                {
                    "id": criterion["id"],
                    "score": score,
                    "verdict": "pass" if score >= points * 0.8 else "partial",
                    "evidence": f"[00:1{rng.randint(0, 9)}] — stub dalil ({criterion['id']})",
                    "improvement": None if score == points else "Yaxshilash mumkin",
                }
            )
        blocks[block["key"]] = {"score": block_total, "criteria": criteria}
        total += block_total

    known = {f["type"]: f for f in rubric_red_flags}
    flags = []
    penalty = 0
    zeroed = False
    for flag_type in red_flags:
        spec = known.get(flag_type)
        if spec is None:
            continue
        penalty += int(spec.get("penalty", 0))
        zeroed = zeroed or bool(spec.get("zeroes_score"))
        flags.append(
            {
                "type": flag_type,
                "severity": "high",
                "timestamp": "07:42",
                "quote": "stub iqtibos",
            }
        )
    if invented_flag:
        flags.append(
            {
                "type": invented_flag,
                "severity": "high",
                "timestamp": "03:11",
                "quote": "stub iqtibos",
            }
        )

    overall = 0 if zeroed else max(0, min(100, total + penalty))

    return {
        "language_detected": "mixed",
        "transcript_quality": quality,
        "blocks": blocks,
        "red_flags": flags,
        "outcome_signal": {
            "type": "follow_up",
            "products_mentioned": ["X-200", "Y-50"],
            "quantity_mentioned": 50,
            "confidence": 0.7,
            "evidence": "[00:58] — «Mayli, ertaga aytaman»",
        },
        "client_sentiment": "neutral",
        "coaching_note": (
            "Mahsulot yaxshi taqdim etildi. E'tiroz bilan ishlashni "
            "kuchaytiring: narx e'tirozidan keyin qiymat argumenti kerak edi."
        ),
        "confidence": confidence,
        "call_scenario": "repeat_order",
        # The model is no longer asked for this (it is absent from the schema),
        # but a provider may still send it — the validator must ignore it.
        "overall_score": overall if overall_override is None else overall_override,
    }
