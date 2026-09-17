"""The 100-point rubric, pinned in code for phase 1 (SPEC-ANALYTICS §2.5).

**This file is allow-listed for Uzbek text** (CONVENTIONS.md §14, SPEC-ANALYTICS
§1.6). The criterion labels and descriptions are not messages a user reads — they
are what the model matches the conversation against, and their language was
chosen by measuring output quality on Uzbek and code-switched Uzbek/Russian
speech. Translating them would be an untested change to the product's most
sensitive input. Comments and docstrings around them are English like everywhere
else.

Rule: the blocks total **exactly 100**. BonviZvonki enforced that in
``RubricService._validate`` when an admin saved a rubric; phase 1 has no such
screen, so ``tests/test_scoring.py`` asserts it instead.

## ``optional`` — A CRITERION DOES NOT APPLY TO EVERY CONVERSATION

Every criterion carries an ``optional`` flag. When it is ``True`` the model may
mark that criterion "does not apply to this conversation" (``na``) and it is
**excluded** from the arithmetic.

WHY IT EXISTS. Most Bonvi customers are **returning** customers. They do not
talk through a script: "brother, send me 50 of them" or "send the new prices"
and they are done inside a minute. In a conversation like that there is no need
to establish requirements, no need to present the product and no need for a
value argument — the customer knows what they are buying and has already bought
it.

Check such a call against the full sales script and the employee scores 40-50
through no fault of their own: they did everything right, but half the rubric
has nothing to do with this conversation. A low score like that says nothing
about the employee and everything about the RUBRIC.

The fix: a criterion that does not apply does not score zero — it is not counted
at all, and the score is computed **within the criteria that were applied** (see
``validator.py``).

``optional: False`` marks a criterion that lands on any conversation at all:
greeting, courtesy, answering the question that was asked, and being concrete
about what happens next. Those cannot be marked inapplicable, or nothing would
be left and every call would score 100.
"""

from typing import Any

#: Stamped on every score row. Changing ``DEFAULT_RUBRIC`` means bumping this in
#: the same commit: a modified rubric under an unchanged version makes two
#: scores incomparable while claiming they are comparable (§2.5). Phase 2 reads
#: the active rubric row instead, and every phase-1 score already carries "v1",
#: so nothing needs back-filling.
RUBRIC_VERSION = "v1"

DEFAULT_RUBRIC: dict[str, Any] = {
    "name": "Bonvi savdo rubrikasi v1",
    "description": (
        "Savdo direktori bilan kelishilgan boshlang'ich rubrika. "
        "Har oyda ko'rib chiqilishi tavsiya etiladi."
    ),
    "blocks": [
        {
            "key": "script",
            "label": "Skript va struktura",
            "max": 25,
            "criteria": [
                {
                    "id": "A1",
                    "label": "Salomlashish va o'zini tanishtirish",
                    "points": 5,
                    "optional": False,
                    "description": (
                        "«Assalomu alaykum, men [ism], Bonvi kompaniyasidan». "
                        "Tanish mijoz bilan to'liq tanishtirish shart emas — "
                        "xushmuomala salomlashish yetarli."
                    ),
                },
                {
                    "id": "A2",
                    "label": "Ehtiyojni aniqlash",
                    "points": 8,
                    "optional": True,
                    "description": (
                        "Ochiq savollar berdimi, mahsulot ehtiyojini so'radimi. "
                        "Mijoz o'zi aniq buyurtma aytgan bo'lsa (masalan «50 ta "
                        "chiqaring») — bu mezon TAALLUQLI EMAS."
                    ),
                },
                {
                    "id": "A3",
                    "label": "Mahsulotni to'g'ri taqdim etish",
                    "points": 7,
                    "optional": True,
                    "description": (
                        "Model, xususiyat va narx to'g'ri aytildi. Mijoz "
                        "mahsulotni allaqachon biladi va faqat qoldiq/narx "
                        "so'ragan bo'lsa — taalluqli emas."
                    ),
                },
                {
                    "id": "A4",
                    "label": "Keyingi qadam kelishildi",
                    "points": 5,
                    "optional": False,
                    "description": (
                        "Suhbat osilgan holda tugamadi: buyurtma tasdiqlandi, "
                        "sana aytildi yoki «qayta qo'ng'iroq qilaman» deyildi."
                    ),
                },
            ],
        },
        {
            "key": "communication",
            "label": "Muloqot madaniyati",
            "max": 25,
            "criteria": [
                {
                    "id": "B1",
                    "label": "Hurmatli ohang",
                    "points": 8,
                    "optional": False,
                    "description": "Siz'lash, xushmuomalalik",
                },
                {
                    "id": "B2",
                    "label": "Haqorat va so'kinish yo'q",
                    "points": 10,
                    "optional": False,
                    "description": "Buzilsa — umumiy ball 0 ga tushadi",
                },
                {
                    "id": "B3",
                    "label": "Client'ni bo'lmadi",
                    "points": 4,
                    "optional": False,
                    "description": "Overlap va bo'lish soni akustik tahlildan olinadi",
                },
                {
                    "id": "B4",
                    "label": "Ovoz toni mos",
                    "points": 3,
                    "optional": False,
                    "description": "Prosodika: baqirish yoki asabiylik belgilari",
                },
            ],
        },
        {
            "key": "resolution",
            "label": "Muammoni hal qilish",
            "max": 25,
            "criteria": [
                {
                    "id": "C1",
                    "label": "Client savoliga to'g'ri javob berdi",
                    "points": 10,
                    "optional": False,
                    "description": (
                        "Ma'lumot aniq va to'liq. Qisqa suhbatda ham shu mezon "
                        "ishlaydi: mijoz nima so'ragan bo'lsa, javob olganmi."
                    ),
                },
                {
                    "id": "C2",
                    "label": "E'tirozlarni ishlab chiqdi",
                    "points": 8,
                    "optional": True,
                    "description": (
                        "Narx, muddat, sifat e'tirozlariga javob. Mijoz e'tiroz "
                        "bildirmagan bo'lsa — taalluqli emas."
                    ),
                },
                {
                    "id": "C3",
                    "label": "Mos taklif berdi",
                    "points": 7,
                    "optional": True,
                    "description": (
                        "Mahsulot client ehtiyojiga to'g'ri keldi. Mijoz aniq "
                        "mahsulotni o'zi so'ragan bo'lsa — taalluqli emas."
                    ),
                },
            ],
        },
        {
            "key": "sales_skill",
            "label": "Savdo qobiliyati",
            "max": 25,
            "criteria": [
                {
                    "id": "D1",
                    "label": "Yopish urinishi",
                    "points": 8,
                    "optional": True,
                    "description": (
                        "«Nechta olamiz?» — suhbat osilgan holda tugamadi. "
                        "Mijozning o'zi buyurtma bergan bo'lsa, yopish "
                        "allaqachon bo'lgan — taalluqli emas."
                    ),
                },
                {
                    "id": "D2",
                    "label": "Upsell / cross-sell",
                    "points": 6,
                    "optional": True,
                    "description": (
                        "Qo'shimcha model yoki miqdor taklif qilindi. Bir "
                        "daqiqalik qoldiq/narx so'rovida taalluqli emas."
                    ),
                },
                {
                    "id": "D3",
                    "label": "Aniq keyingi qadam",
                    "points": 6,
                    "optional": False,
                    "description": (
                        "«Payshanba qo'ng'iroq qilaman», «ertaga jo'natamiz» — "
                        "mavhum emas, aniq."
                    ),
                },
                {
                    "id": "D4",
                    "label": "Qiymat argumenti",
                    "points": 5,
                    "optional": True,
                    "description": (
                        "Nega aynan hozir olish kerakligi asoslandi. Mijoz "
                        "allaqachon sotib olayotgan bo'lsa — taalluqli emas."
                    ),
                },
            ],
        },
    ],
    "red_flags": [
        {
            "type": "profanity",
            "label": "Haqorat / so'kinish",
            "penalty": -100,
            "zeroes_score": True,
            "description": "Umumiy ball 0 ga tushadi va menejerga darhol xabar boradi",
        },
        {
            "type": "off_policy_deal",
            "label": "Qoidadan tashqari kelishuv",
            "penalty": -25,
            "zeroes_score": False,
            "description": "Rasmiy narxdan tashqari shaxsiy kelishuv",
        },
        {
            "type": "shouting",
            "label": "Baqirish",
            "penalty": -20,
            "zeroes_score": False,
            "description": "Prosodika + matn konteksti birgalikda tasdiqlaydi",
        },
        {
            "type": "unrealistic_promise",
            "label": "Bajarilmas va'da",
            "penalty": -15,
            "zeroes_score": False,
            "description": "Bajarib bo'lmaydigan muddat yoki shart va'da qilindi",
        },
        {
            "type": "badmouthing",
            "label": "Salbiy gap (kompaniya / hamkasb)",
            "penalty": -15,
            "zeroes_score": False,
            "description": "Client oldida kompaniya yoki hamkasb haqida salbiy fikr",
        },
        {
            "type": "ignored_complaint",
            "label": "Shikoyat e'tiborsiz qoldirilgan",
            "penalty": -10,
            "zeroes_score": False,
            "description": "Client muammo aytdi, javob berilmadi",
        },
    ],
}
