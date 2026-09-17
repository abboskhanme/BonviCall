"""The scoring prompt — THE PRODUCT ITSELF.

**This file is allow-listed for Uzbek text** (CONVENTIONS.md §14, SPEC-ANALYTICS
§1.6). Every string below is model input, not a message a person reads; its
wording was tuned against real Uzbek and code-switched Uzbek/Russian calls, and
translating it would be an untested change to the most sensitive input this
product has. Comments and docstrings are English like everywhere else, and no
comment here reaches the model.

Deliberately separate from the pipeline: tuning the prompt is weekly work, while
the pipeline logic barely changes. The sales director edits the text here and
``pipeline.py`` is not touched.

Three hard rules:

1. **The prompt is built from the rubric**, never retyped by hand. When the
   rubric changes the prompt changes with it — otherwise the LLM would score
   against the old criteria while the validator checked against the new ones.
2. **The system prompt is byte-stable** (prompt caching). The date, the call id
   and the employee's name all live in the USER message. Otherwise the cache
   never hits and the rubric's tokens are paid for on every single call.
3. **The language is Uzbek.** Calls are mixed Uzbek/Russian (code switching) and
   the prompt says so openly — otherwise the model marks the Russian sentences
   "unintelligible" and penalises the employee for nothing.

Pure: imports ``typing.Any`` and nothing else
(``tests/test_analysis_purity.py``).
"""

from typing import Any

# -- The blocks and red flags, rendered as text ----------------------------


def _render_blocks(blocks: list[dict[str, Any]]) -> str:
    """Render the rubric as text.

    WARNING: every criterion SHOWS its ``optional`` mark. That mark is how the
    model learns "this criterion may be marked as not applicable" — without it
    the model would be forced to put a zero on every criterion even in a short
    conversation.
    """
    lines: list[str] = []
    for block in blocks:
        lines.append(
            f"\n### Blok «{block.get('label', block['key'])}» "
            f"(kalit: `{block['key']}`, maksimal {block.get('max', 0)} ball)"
        )
        for criterion in block.get("criteria", []):
            description = criterion.get("description") or ""
            mark = (
                "  ⟨taalluqli bo'lmasa `na`⟩"
                if criterion.get("optional")
                else "  ⟨HAR DOIM baholanadi⟩"
            )
            lines.append(
                f"  · {criterion['id']} — {criterion.get('label', '')} "
                f"[0..{criterion.get('points', 0)} ball]{mark}"
                + (f". {description}" if description else "")
            )
    return "\n".join(lines)


def _render_red_flags(red_flags: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for flag in red_flags:
        note = " — umumiy ball 0 ga tushadi" if flag.get("zeroes_score") else ""
        description = flag.get("description") or ""
        lines.append(
            f"  · `{flag['type']}` — {flag.get('label', '')} "
            f"({flag.get('penalty', 0)} ball{note})"
            + (f". {description}" if description else "")
        )
    return "\n".join(lines)


# -- The system prompt -----------------------------------------------------


#: Ceiling on the admin's extra instructions, in characters.
#
# WHY THERE IS A CEILING. This text is added to the prompt on EVERY call, so its
# length converts directly into money: 4000 characters is roughly 1200 tokens,
# which at ~15 000 calls a month is 18 million input tokens. An unbounded field
# is one somebody pastes an entire staff handbook into, and nothing would stop
# them.
MAX_EXTRA_RULES = 4000


def _render_extra_rules(extra_rules: str | None) -> str:
    """Add the admin's instructions as a section of their own.

    When it is empty the WHOLE section disappears, heading included. Left with
    an empty heading, the model may decide something was supposed to be there
    and invent the missing instruction.
    """
    text = (extra_rules or "").strip()
    if not text:
        return ""
    # One blank line before and after: the separation around this section has
    # to match the rubric and rules sections, otherwise the markdown headings
    # run into each other and the model may misread the section boundaries.
    return f"""
## KOMPANIYANING QO'SHIMCHA QOIDALARI

Quyidagilarni admin yozgan. Ular RUBRIKAGA QO'SHIMCHA: mavjud
kriteriyalar va red flag'larni bekor qilmaydi, balki nimaga alohida
e'tibor berishni ko'rsatadi.

{text}

⚠️ Yuqoridagi qoidalar javob SHAKLINI o'zgartirmaydi. Ular bilan
pastdagi ball qo'yish tartibi yoki JSON shakli o'rtasida ziddiyat
bo'lsa — PASTDAGISI ustun turadi.
"""


def build_system_prompt(
    rubric_blocks: list[dict[str, Any]],
    rubric_red_flags: list[dict[str, Any]],
    extra_rules: str | None = None,
) -> str:
    """Build the system prompt from the rubric.

    It depends on the rubric alone — the same rubric always produces the same
    text, which is what prompt caching requires. ``extra_rules`` is part of the
    rubric too: while it does not change, the text does not change.

    WARNING: WHERE THE ADMIN'S TEXT GOES is not accidental. It sits AFTER the
    rubric and BEFORE the scoring rules and the RESPONSE FORMAT. The reason: on
    a conflict an LLM usually follows the later instruction, so the format
    contract has to come last. Put the admin's text at the end and a casually
    written "explain your answer in prose" would break the JSON and no score
    would pass validation — one edit stopping all scoring.
    """
    parts = _sections(rubric_blocks, rubric_red_flags, extra_rules)
    return "".join(part["text"] for part in parts)


def split_system_prompt(
    rubric_blocks: list[dict[str, Any]],
    rubric_red_flags: list[dict[str, Any]],
    extra_rules: str | None = None,
) -> list[dict[str, Any]]:
    """The prompt as a list of named sections.

    WARNING: built from the SAME SOURCE as ``build_system_prompt`` (``_sections``).
    Written as two separate functions they would drift apart over time: the
    admin page would show one text while the AI received another — the worst
    kind of bug, because it has no symptom.
    """
    return _sections(rubric_blocks, rubric_red_flags, extra_rules)


def _sections(
    rubric_blocks: list[dict[str, Any]],
    rubric_red_flags: list[dict[str, Any]],
    extra_rules: str | None,
) -> list[dict[str, Any]]:
    """Every section of the prompt, IN ORDER.

    The order matters: the admin's text comes after the rubric and before the
    rules and the format (the reason is in ``build_system_prompt``).
    """
    block_keys = ", ".join(f"`{b['key']}`" for b in rubric_blocks)
    flag_keys = ", ".join(f"`{f['type']}`" for f in rubric_red_flags)
    total = sum(int(b.get("max", 0)) for b in rubric_blocks)

    return [
        # The backslash keeps the string byte-identical while letting the
        # opening line stay inside the line limit: `"""\` swallows the newline
        # that would otherwise start the prompt.
        {"key": "intro", "editable": False, "text": """\
Siz — Bonvi kompaniyasining savdo sifati bo'yicha tajribali auditorisiz.
Vazifangiz: savdo xodimining mijoz bilan telefon suhbati transkriptini
quyidagi rubrika bo'yicha xolis baholash.

## TIL HAQIDA — DIQQAT

Qo'ng'iroqlar O'ZBEK va RUS tillarida, ko'pincha ARALASH olib boriladi
(bir gapda ikkala til: «Assalomu alaykum, я по поводу заказа»).
Bu — O'zbekistonda MEYOR, kamchilik EMAS.

  · Til aralashtirilgani uchun ball KAMAYTIRILMAYDI.
  · Rus tilidagi gap ham xuddi o'zbekchadek to'liq baholanadi.
  · Transkriptda so'z buzilgan bo'lishi mumkin (nutqni matnga o'girish
    xatosi). Ma'no kontekstdan tushunarli bo'lsa — xodim aybdor emas.
  · Mahsulot nomi yoki raqam buzilgan ko'rinsa, buni xodimning xatosi
    deb hisoblamang; `transcript_quality` ni pasaytiring.

Sizning javobingiz — o'zbek tilida. Dalil (evidence) va iqtibos (quote)
esa transkriptdagi ASL tilda, o'zgartirilmasdan keltiriladi.

"""},
        {"key": "rubric", "editable": False, "text": f"""## RUBRIKA (jami {total} ball)
{_render_blocks(rubric_blocks)}

## RED FLAG'LAR (faqat shu kalitlar)
{_render_red_flags(rubric_red_flags)}
"""},
        {"key": "context", "editable": False, "text": """
## SUHBAT KONTEKSTI — ENG MUHIM QOIDA

Bonvi mijozlarining KO'PCHILIGI eski, doimiy mijoz: do'kon egasi,
usta, ulgurji xaridor. Ular skript bo'yicha gaplashmaydi va ularga
skript KERAK EMAS. Odatiy qo'ng'iroq shunday ko'rinadi:

  «Aka, menga o'sha 50 tadan chiqarib qo'ying»
  «Yangi narxlarni tashlang»
  «Metan bormi hozir? Ertaga borsam bo'ladimi?»

Bunday suhbat 30 soniyada tugaydi va bu YAXSHI ish. Mijoz nima
olishini biladi, xodim tez va aniq javob berdi — savdo bo'ldi.

⚠️ SHUNDAY SUHBATNI TO'LIQ SKRIPT BO'YICHA TEKSHIRMANG. «Ehtiyojni
aniqlamadi», «mahsulotni taqdim etmadi», «upsell qilmadi» deb ball
kesish — XATO baho. Bu mezonlar shu suhbatga umuman TAALLUQLI EMAS,
xodim esa hamma ishni to'g'ri qilgan.

### `na` — «taalluqli emas»

Rubrikada ⟨taalluqli bo'lmasa `na`⟩ deb belgilangan kriteriyalarga
`verdict: "na"` va `score: 0` qo'yish MUMKIN. Bunday kriteriya ball
hisobidan butunlay chiqariladi: u nol ham olmaydi, maksimum ham
olmaydi — go'yo rubrikada yo'q. Umumiy ball QOLGAN, ya'ni haqiqatan
qo'llanilgan mezonlar ichida hisoblanadi.

`na` QACHON to'g'ri bo'ladi:
  · mijoz aniq buyurtma aytdi → ehtiyojni aniqlash kerak emas (A2);
  · mijoz mahsulotni biladi, faqat qoldiq/narx so'radi → taqdim
    etish kerak emas (A3);
  · e'tiroz umuman bildirilmadi → e'tiroz bilan ishlash yo'q (C2);
  · mijozning o'zi sotib olyapti → yopish urinishi shart emas (D1);
  · qisqa texnik so'rov → upsell va qiymat argumenti o'rinsiz (D2, D4).

`na` QACHON NOTO'G'RI:
  · xodim mezonni bajarishi MUMKIN va FOYDALI edi, lekin bajarmadi —
    bu `fail`, `na` emas. Farqi shu: `na` — «vaziyat talab qilmadi»,
    `fail` — «vaziyat imkon berdi, xodim foydalanmadi». Masalan
    mijoz buyurtma bergach «yana nima kerak edi?» deb so'rash real
    imkoniyat edi — bunda upsell `na` emas, `fail`;
  · ⟨HAR DOIM baholanadi⟩ deb belgilangan kriteriya. Salomlashish,
    muomala madaniyati, savolga to'g'ri javob va kelishuvning
    aniqligi HAR QANDAY suhbatda tekshiriladi — eng qisqasida ham;
  · suhbat UZUN bo'lsa (2 daqiqadan ortiq) `na` kamdan-kam to'g'ri
    bo'ladi: vaqt bo'lgan, demak bosqichlar ham bo'lishi mumkin edi.

Har bir `na` uchun `evidence` da SABAB yoziladi: nega bu mezon shu
suhbatga tegishli emas. Sababsiz `na` — yashirin ball ko'tarish.

### ⚠️ `na` — MEZON TANLASHDAGI yengillik, BALL QO'YISHDAGI emas

Bu ikkisini ARALASHTIRMANG. Qaysi mezon qo'llanishini vaziyat hal
qiladi; qo'llanadigan mezon esa HAR DOIMGIDEK qat'iy baholanadi.

Ya'ni «suhbat qisqa edi, mayli, hammasiga to'liq ball qo'yaman» —
XATO. Qisqa suhbatda ham xodim salomlashmasligi, kompaniya nomini
aytmasligi, mijozni bo'lishi yoki kelishuvni mavhum qoldirishi
mumkin. Bularning har biri o'z mezonida ball yo'qotadi.

To'liq ball (maksimum) faqat mezon TO'LIQ bajarilganda qo'yiladi.
Agar `improvement` maydonida «... qilsa yaxshi bo'lardi» deb yozsangiz,
demak mezon to'liq bajarilmagan — u holda ball maksimal BO'LMAYDI.
Bu ikkisi bir-biriga zid va shunday javob ishonchsiz ko'rinadi.

### Qisqalik kamchilik EMAS

Suhbatning qisqaligi uchun ball kesilmaydi. Savol shu emas: «xodim
ko'p gapirdimi?» Savol shu: «mijoz nima uchun qo'ng'iroq qilgan
bo'lsa, o'shani oldimi va bunda unga hurmat bilan muomala qilindimi?»
Agar javob «ha» bo'lsa — bu yuqori ball, suhbat 20 soniya bo'lsa ham.

`call_scenario` maydonida suhbat qanday bo'lganini belgilang — menejer
`na` qarorlarini shu bilan tekshiradi.
"""},
        {
            "key": "extra_rules",
            "editable": True,
            "text": _render_extra_rules(extra_rules),
        },
        {"key": "rules", "editable": False, "text": f"""
## BALL QO'YISH QOIDALARI

1. Har bir kriteriyaga 0 dan uning maksimal balligacha butun son qo'ying.
   Kriteriya shu suhbatga taalluqli bo'lmasa (va rubrikada ⟨taalluqli
   bo'lmasa `na`⟩ deb belgilangan bo'lsa) — `verdict: "na"`, `score: 0`.

   Verdikt va ball BIR XIL narsani aytishi kerak:
     · `pass`    — mezon TO'LIQ bajarilgan, transkriptda aniq dalil bor
                   → maksimal ball;
     · `partial` — qisman bajarilgan yoki dalil kuchsiz → maksimumning
                   yarmi atrofida;
     · `fail`    — bajarilmagan → 0 yoki juda kam;
     · `na`      — vaziyat talab qilmagan → 0, hisobga kirmaydi.

   ⚠️ Maksimal ball ISBOT talab qiladi. Transkriptda mezonni tasdiqlovchi
   aniq iqtibos bo'lmasa, `pass` ham, maksimal ball ham qo'yilmaydi —
   `partial` qo'ying. «Yomon narsa ko'rmadim» — bu dalil emas.
2. Blok baliga va umumiy ballga SIZ TEGMAYSIZ — ular kriteriya
   ballaridan hisoblanadi. Sizning ishingiz faqat har bir mezonga
   halol ball va halol verdikt qo'yish.

   ⚠️ FOYDALANUVCHI XABARIDA `na` UCHUN CHEGARA ko'rsatiladi va u shu
   suhbat uzunligidan kelib chiqadi. Qisqa suhbatda chegara amalda
   yo'q, uzun suhbatda esa kichik: 8 daqiqa gaplashilgan bo'lsa,
   ehtiyojni aniqlash ham, taqdimot ham, e'tiroz bilan ishlash ham
   BO'LISHI MUMKIN edi — ular «taalluqli emas» emas, «qilinmagan».
   Chegaradan oshsa javob rad etiladi va qayta so'raladi.

   ⚠️ `na` MEZONNING BALLI BOSHQA MEZONLARGA TAQSIMLANMAYDI. Blok
   maksimumini «to'ldirish» kerak emas: A2 va A3 taalluqli bo'lmasa,
   qolgan mezonlarning bali oshmaydi — ular baribir foizga
   aylantiriladi va xodim yutqazmaydi. Hech bir mezon o'z
   maksimumidan oshiq ball ololmaydi.
3. Umumiy ball shunday hisoblanadi: qo'llanilgan mezonlar bo'yicha
   olingan ball ularning maksimumiga nisbatan foizga aylantiriladi,
   keyin red flag jarimalari ayiriladi.
4. Har bir kriteriya uchun DALIL majburiy: transkriptdan qisqa iqtibos.
   Vaqt belgisi bor bo'lsa (`[04:12]`) uni ham keltiring. Dalil topilmasa
   ball past bo'ladi va `evidence` da «dalil topilmadi» deb yoziladi.
   `na` uchun `evidence` da NEGA taalluqli emasligi yoziladi.
   HECH QACHON transkriptda yo'q gapni o'ylab topmang.
5. Red flag faqat quyidagi kalitlardan biri bo'lishi mumkin: {flag_keys}.
   Boshqa kalit yozilsa — butun javob rad etiladi. Red flag har doim
   iqtibos bilan tasdiqlanadi; shubha bo'lsa — QO'YMANG.
   Bir xil tur bir necha marta takrorlansa — HAR BIR hodisani alohida
   yozing (o'z vaqti va o'z iqtiboti bilan). Menejer nima bo'lganini
   to'liq ko'rishi kerak; jarima esa baribir bir marta hisoblanadi.
   `profanity` bo'lsa umumiy ball 0 ga tushadi.
6. Baqirish (`shouting`) faqat matndan aniqlanmaydi. Transkriptda
   ochiq-oydin dalil (BOSH HARFLAR, «nega baqiryapsiz» degan javob)
   bo'lmasa — qo'ymang.
7. `confidence` — o'z bahoingizga ishonch (0..1). Transkript qisqa,
   uzuq-yuluq yoki mijoz gapi yetishmasa — 0.7 dan past qo'ying.
   ⚠️ Suhbat SHUNCHAKI qisqa bo'lgani (mijoz tez buyurtma berib
   qo'ygani) ishonchni pasaytirmaydi — bunda hammasi tushunarli.
   Ishonch transkript SIFATI haqida, suhbat uzunligi haqida emas.
8. `outcome_signal` — zakaz belgisi. Bu BALL EMAS, faqat signal;
   ishonchingiz past bo'lsa `unclear` deb belgilang.
9. `call_scenario` — suhbat qanday bo'ldi: `new_client` (yangi mijoz,
   to'liq tanishtirish talab qilinadi), `repeat_order` (tanish mijoz
   buyurtma berdi), `price_check` (qoldiq/narx so'rovi), `issue`
   (shikoyat, muammo, yetkazib berish), `personal` (ishga aloqasi
   yo'q suhbat), `no_content` (suhbatda ish mazmuni UMUMAN yo'q),
   `other`. Bu maydon `na` qarorlaringizni tushuntiradi.

   ⚠️ `no_content` — ALOHIDA HOLAT. Ba'zi qo'ng'iroqlarda baholash
   uchun material yo'q: salomlashib «keyinroq qo'ng'iroq qilaman» deb
   tugaydi, noto'g'ri raqam, aloqa uzilgan, faqat hol-ahvol so'rashilgan.
   Bunday suhbatga yuqori ball qo'yish ko'rsatkichni YOLG'ON qiladi —
   xuddi past ball qo'ygandek zararli. Shuning uchun `no_content` da
   `confidence` ni 0.6 dan PAST qo'ying: bu «material yetarli emas»
   degan signal va menejer bunday bahoni tekshiruv navbatida ko'radi.
10. `coaching_note` — xodimga 2–3 jumlalik amaliy maslahat, o'zbek
   tilida. Ayblov emas, o'sish uchun ko'rsatma: nima yaxshi, nimani
   qanday yaxshilash mumkin. Suhbat qisqa va to'g'ri o'tgan bo'lsa —
   buni tan oling, sun'iy kamchilik izlamang.

Bu baho — KOUCHING vositasi. Odamning ishi haqidagi qaror emas.
Shubhali holatda xodim foydasiga hal qiling va `confidence` ni pasaytiring.

"""},
        {"key": "format", "editable": False, "text": f"""## JAVOB SHAKLI

Faqat JSON qaytaring. Izoh, markdown belgilari va matn — YO'Q.
Bloklar kalitlari aynan shular: {block_keys}.

Ikkita eng ko'p uchraydigan xato — javob shu sababli rad etiladi:

  · HAR BIR kriteriya javobda BO'LISHI SHART, `na` deb belgilangani
    HAM. Uni ro'yxatdan tushirib qoldirmang: `na` — bu javob, «javob
    yo'q» emas.
  · `verdict: "na"` faqat rubrikada ⟨taalluqli bo'lmasa `na`⟩ deb
    belgilangan kriteriyada bo'ladi. ⟨HAR DOIM baholanadi⟩ da `na`
    qo'yilsa butun javob rad etiladi — u yerda `fail` yoki `partial`
    ishlatiladi."""},
    ]


# -- The user message ------------------------------------------------------


def build_user_prompt(
    *,
    transcript: str,
    duration_sec: int,
    direction: str,
    started_at: str,
    client_label: str | None = None,
    na_budget: int | None = None,
) -> str:
    """One call. The part that sits AFTER the cache boundary.

    WARNING: ``client_label`` is a signal for IS THIS CUSTOMER KNOWN, not the
    name itself. A name is only present when the number is in the contact book,
    which means we have dealt with this number before. That matters to the
    score: a known customer needs neither a full introduction nor requirements
    established from scratch.
    """
    direction_uz = (
        "Chiquvchi (xodim qo'ng'iroq qilgan)"
        if direction == "outbound"
        else "Kiruvchi (mijoz qo'ng'iroq qilgan)"
    )
    minutes, seconds = divmod(max(duration_sec, 0), 60)

    header = [
        "## QO'NG'IROQ",
        f"Sana: {started_at}",
        f"Yo'nalish: {direction_uz}",
        f"Davomiyligi: {minutes} daq {seconds} son",
    ]
    if na_budget is not None:
        # WARNING: the budget is for THIS call specifically — it depends on the
        # length. Left without a ceiling the model dropped seven criteria even
        # in a ten-minute conversation and handed out 100.
        header.append(
            f"⚠️ `na` CHEGARASI: {na_budget} ball. `na` deb belgilangan "
            "mezonlarning BALLARI yig'indisi shundan oshmasligi kerak "
            "(masalan 6 + 5 = 11 — mumkin; 8 + 7 + 8 = 23 — mumkin emas). "
            "Chegara shu suhbatning uzunligidan kelib chiqadi: vaqt "
            "bo'lgan bo'lsa, bosqich ham bo'lishi mumkin edi. Oshib "
            "ketsa javob RAD ETILADI."
        )
    if client_label:
        header.append(
            f"Mijoz: {client_label} — TANISH mijoz (kontaktlar kitobida "
            "saqlangan, ya'ni u bilan ilgari ham ishlangan)"
        )
    else:
        header.append(
            "Mijoz: kontaktlar kitobida yo'q — yangi yoki tasodifiy raqam "
            "bo'lishi mumkin"
        )

    return (
        "\n".join(header)
        + "\n\n## TRANSKRIPT\n\n"
        + (transcript or "").strip()
        + "\n\n## VAZIFA\n"
        + "Yuqoridagi rubrika bo'yicha baholang va faqat JSON qaytaring."
    )


def build_retry_prompt(previous_error: str) -> str:
    """The addendum to the second request after an answer failed validation."""
    return (
        "\n\n## ⚠️ OLDINGI JAVOBINGIZ RAD ETILDI\n"
        f"Sabab: {previous_error}\n"
        "Xatoni tuzatib, YANA BIR BOR to'liq JSON qaytaring. "
        "Har blokda `na` bo'lmagan kriteriyalar yig'indisi blok baliga "
        "aniq teng bo'lsin. `overall_score` ni qaytarish shart emas — "
        "uni tizim o'zi hisoblaydi."
    )


# -- The structured-output schema ------------------------------------------


def build_schema(
    rubric_blocks: list[dict[str, Any]], rubric_red_flags: list[dict[str, Any]]
) -> dict[str, Any]:
    """The JSON Schema handed to ``LLMClient.complete(schema=...)``.

    Built from the rubric: the block keys and the red-flag types are exactly
    the rubric's, so the model cannot return an invented key. (On providers
    with no schema support the schema is appended to the prompt instead.)
    """
    block_properties: dict[str, Any] = {}
    for block in rubric_blocks:
        criteria_properties: dict[str, Any] = {}
        for criterion in block.get("criteria", []):
            points = int(criterion.get("points", 0))
            optional = bool(criterion.get("optional"))
            # WARNING: the verdict list is PER CRITERION. `na` only exists on an
            # optional one and the schema itself blocks the rest — it never
            # reaches the validator, which means no second request and no second
            # bill.
            verdicts = ["pass", "partial", "fail"] + (["na"] if optional else [])
            criteria_properties[criterion["id"]] = {
                "type": "object",
                "description": (
                    f"{criterion.get('label', '')} — 0..{points} ball"
                    + (
                        ". Taalluqli bo'lmasa: verdict=na, score=0"
                        if optional
                        else ". Har qanday suhbatda baholanadi"
                    )
                ),
                "properties": {
                    # WARNING: the ceiling is THIS criterion's own.
                    #
                    # WHY IT MATTERS. The criteria used to arrive as an array
                    # with one shared ceiling. Once `na` existed the model tried
                    # to REDISTRIBUTE the dropped criterion's points across the
                    # rest: it put 15 on A4 instead of 5, to "fill up" the block
                    # maximum. The validator rejected it, the model tried again,
                    # and two calls in five ended up unscored (three requests =
                    # three payments, no result).
                    #
                    # As an object every criterion gets its own ceiling and an
                    # answer like that is structurally impossible.
                    "score": {"type": "integer", "minimum": 0, "maximum": points},
                    "verdict": {"type": "string", "enum": verdicts},
                    "evidence": {"type": "string"},
                    "improvement": {"type": "string"},
                },
                "required": ["score", "verdict", "evidence"],
                "additionalProperties": False,
            }

        block_properties[block["key"]] = {
            "type": "object",
            "description": f"{block.get('label', '')} — {block.get('max', 0)} ball",
            "properties": {
                # WARNING: there is no `score` field and its absence is
                # deliberate. The block score is the sum of the criteria, i.e. a
                # COMPUTED value. Asking the model for it was only ever a source
                # of errors: after a criterion was dropped with `na` it tried to
                # "fill up" the block maximum and the answer was rejected.
                "criteria": {
                    "type": "object",
                    "properties": criteria_properties,
                    # Every criterion is REQUIRED — including the `na` ones.
                    # The model used to leave them out of the list.
                    "required": list(criteria_properties),
                    "additionalProperties": False,
                }
            },
            "required": ["criteria"],
            "additionalProperties": False,
        }

    flag_types = [f["type"] for f in rubric_red_flags]

    return {
        "type": "object",
        "properties": {
            "language_detected": {
                "type": "string",
                "enum": ["uz", "ru", "mixed", "other"],
            },
            "transcript_quality": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "blocks": {
                "type": "object",
                "properties": block_properties,
                "required": list(block_properties),
                "additionalProperties": False,
            },
            "red_flags": {
                "type": "array",
                # One element per INCIDENT: the same `type` may appear several
                # times (each with its own timestamp and quote). The penalty is
                # counted once per type, which `validator._validate_red_flags`
                # guarantees.
                "description": (
                    "Aniqlangan qoidabuzarliklar. Bir xil tur bir necha marta "
                    "uchrasa — har hodisa alohida element bo'ladi, jarima esa "
                    "`overall_score` da bir marta hisoblanadi."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": flag_types},
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "timestamp": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": ["type", "severity", "quote"],
                    "additionalProperties": False,
                },
            },
            "outcome_signal": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "order_agreed",
                            "follow_up",
                            "rejected",
                            "info_only",
                            "unclear",
                        ],
                    },
                    "products_mentioned": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "quantity_mentioned": {"type": ["integer", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string"},
                },
                "required": ["type", "confidence"],
                "additionalProperties": False,
            },
            "client_sentiment": {
                "type": "string",
                "enum": ["positive", "neutral", "negative"],
            },
            "coaching_note": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            # What kind of conversation this was. NOT a score — the context that
            # explains the `na` decisions: it is where a manager finds the
            # answer to "why were five criteria dropped?".
            "call_scenario": {
                "type": "string",
                "enum": [
                    "new_client",
                    "repeat_order",
                    "price_check",
                    "issue",
                    "personal",
                    # Nothing to assess: a greeting, an agreement to call back,
                    # a wrong number
                    "no_content",
                    "other",
                ],
            },
        },
        # WARNING: `overall_score` is NOT in the list, and its absence is
        # deliberate.
        #
        # The model used to compute the overall score and return it, and the
        # validator used to check the arithmetic. There is now a DIVISION in the
        # calculation (a percentage within the applied criteria), so asking the
        # model for it only raises the odds of a rejected answer and a second
        # request — twice the money. The system computes the overall score; the
        # model's job is an honest score per criterion.
        "required": [
            "language_detected",
            "transcript_quality",
            "blocks",
            "red_flags",
            "outcome_signal",
            "client_sentiment",
            "coaching_note",
            "confidence",
            "call_scenario",
        ],
        "additionalProperties": False,
    }
