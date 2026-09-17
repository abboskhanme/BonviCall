"""Every function in ``contacts/rules.py`` and ``contacts/reader.py``.

No session, no container, no clock (CONVENTIONS.md §13 — every function in a
``rules.py`` must have a test). The cases are the ones BonviZvonki's own tests
document, re-expressed in this repo's style, plus the ones its comments claim
were measured — a claim in a comment that no test pins is a claim that quietly
stops being true.

The Cyrillic/Latin case is the one to read first: it is the defect that made
43 real codes match nothing at all.
"""

from __future__ import annotations

import pytest

from src.modules.contacts.reader import (
    content_columns,
    header_columns,
    looks_like_header,
    parse_contact,
    pick_columns,
    prepare_rows,
    read_contacts_file,
)
from src.modules.contacts.rules import (
    CODE_DIGITS,
    ContactKind,
    ImportMode,
    ParsedContact,
    choose_contact,
    extract_code,
    glued_candidates,
    normalize_code,
    resolve_code,
    selected_by,
    suggest_kind,
)

# ── The letter ────────────────────────────────────────────────


def test_a_latin_k_becomes_the_cyrillic_one() -> None:
    """THE defect of the whole port: on screen the two are identical.

    Compared directly, not one of 43 real codes was found and the system sat
    there reporting "no match". After transliteration, 43 of 43 matched.
    """
    code, _ = extract_code("K00150 Elyor aka")
    assert code == "К00150"
    assert code[0] == "К", "Cyrillic К (U+041A), not Latin K (U+004B)"


def test_a_cyrillic_code_is_left_alone() -> None:
    code, _ = extract_code("К00150 Elyor aka")
    assert code == "К00150"


def test_the_letters_with_no_latin_lookalike_are_not_transliterated() -> None:
    """Latin ``P`` is Cyrillic ``Р``, a DIFFERENT letter. Adding that pair
    would corrupt a real code, so ``П`` and ``Й`` only ever match themselves."""
    assert normalize_code("П", "00373") == "П00373"
    assert normalize_code("Й", "00085") == "Й00085"


# ── Reading a code out of a name ──────────────────────────────


def test_a_short_code_is_left_padded_to_five() -> None:
    assert normalize_code("K", "124") == "К00124"
    assert len(normalize_code("K", "124")) == CODE_DIGITS + 1


def test_a_longer_run_of_digits_is_left_alone() -> None:
    """Shortening it could manufacture some other customer's code."""
    assert normalize_code("K", "028890") == "К028890"


def test_a_code_at_the_end_of_the_name_is_found() -> None:
    """Both positions occur in the real list — 34 at the start, 9 at the end.

    Supporting only one would leave a fifth of the list quietly uncoded.
    """
    code, name = extract_code("Ilyosaka K02404")
    assert code == "К02404"
    assert name == "Ilyosaka"


def test_a_code_at_the_start_leaves_the_human_name() -> None:
    assert extract_code("K00150 Elyor aka") == ("К00150", "Elyor aka")


def test_a_letter_inside_a_word_is_not_a_code() -> None:
    """Nothing alphanumeric may precede the letter, or the ``k`` in
    "Ilyosaka" would start a code."""
    assert extract_code("Ilyosaka 12345") == (None, "Ilyosaka 12345")


def test_two_digits_are_not_a_code() -> None:
    """With ``\\d{1,}`` a note like "K 2 dona" would become a code."""
    assert extract_code("K 2 dona") == (None, "K 2 dona")


def test_three_digits_are_accepted_as_a_mistyped_code() -> None:
    assert extract_code("K 124 Aziz") == ("К00124", "Aziz")


def test_the_first_of_several_codes_wins() -> None:
    """The second is usually a note ("K00150 eski K00151") and there is no way
    to tell which is current; choosing wrong attaches the conversation to the
    wrong customer."""
    code, _ = extract_code("K00150 eski K00151")
    assert code == "К00150"


def test_a_name_that_is_only_a_code_leaves_no_human_name() -> None:
    assert extract_code("K00150") == ("К00150", None)


def test_an_empty_name_yields_nothing() -> None:
    assert extract_code("") == (None, None)
    assert extract_code(None) == (None, None)


def test_separators_around_the_code_are_trimmed() -> None:
    assert extract_code("K00150 - Elyor") == ("К00150", "Elyor")


# ── Glued codes, and why they need confirming ─────────────────


def test_a_glued_code_is_a_candidate_and_not_a_code() -> None:
    """"Bobur Xatirchik02121" — real, and dropping the pattern loses a real
    code. Taken unconfirmed, "Blok 123" would become one too."""
    parsed = parse_contact(name="Bobur Xatirchik02121", phone="+998901112233")
    assert parsed is not None
    assert parsed.code is None
    assert parsed.candidates == (("К02121", "Bobur Xatirchi"),)


def test_an_unconfirmed_glued_candidate_is_not_used() -> None:
    parsed = parse_contact(name="Bobur Xatirchik02121", phone="+998901112233")
    assert parsed is not None
    assert resolve_code(parsed, frozenset()) == (None, parsed.name)


def test_a_confirmed_glued_candidate_is_used() -> None:
    """The SALES SEAM, exercised: when the catalogue lands and confirms the
    code, exactly this happens and no rule in ``rules.py`` changes."""
    parsed = parse_contact(name="Bobur Xatirchik02121", phone="+998901112233")
    assert parsed is not None
    assert resolve_code(parsed, frozenset({"К02121"})) == ("К02121", "Bobur Xatirchi")


def test_glued_candidates_are_only_looked_for_without_a_clear_code() -> None:
    parsed = parse_contact(name="K00150 Bobur Xatirchik02121", phone="+998901112233")
    assert parsed is not None
    assert parsed.code == "К00150"
    assert parsed.candidates == ()


def test_glued_candidates_reads_every_match() -> None:
    assert len(glued_candidates("k02121 va k03000")) == 2


# ── Choosing one record per number ────────────────────────────


def _parsed(name: str, code: str | None = None) -> ParsedContact:
    return ParsedContact(
        phone_key="951730700", code=code, name=name, raw_name=name, phone=None
    )


def test_the_most_frequent_name_wins_with_no_confirmed_code() -> None:
    """Six people's wording is more trustworthy than one person's."""
    bucket = [
        _parsed("Asosiy Ombor Zakas"),
        _parsed("Конт Офес"),
        _parsed("Конт Офес"),
    ]
    assert choose_contact(bucket, frozenset()).raw_name == "Конт Офес"


def test_a_wrong_code_does_not_win_over_the_common_name() -> None:
    """⚠️ THE MEASURED FAILURE. ``+998 95 173 07 00`` is a warehouse line
    written under seven names; one employee had put ``К028890`` against it —
    six digits where the catalogue uses five — and that record won, turning
    the warehouse into a customer called "Аюбхон".

    With an unconfirmed code the rule must not fire. This is what the empty
    ``verified`` set buys until the partner catalogue lands.
    """
    bucket = [
        _parsed("Аюбхон", code="К028890"),
        _parsed("Конт Офес"),
        _parsed("Конт Офес"),
    ]
    assert choose_contact(bucket, frozenset()).raw_name == "Конт Офес"


def test_a_confirmed_code_does_win() -> None:
    bucket = [
        _parsed("Аюбхон", code="К02889"),
        _parsed("Конт Офес"),
        _parsed("Конт Офес"),
    ]
    assert choose_contact(bucket, frozenset({"К02889"})).raw_name == "Аюбхон"


def test_a_tie_keeps_the_file_order() -> None:
    bucket = [_parsed("Birinchi"), _parsed("Ikkinchi")]
    assert choose_contact(bucket, frozenset()).raw_name == "Birinchi"


# ── Suggesting a kind ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "known", "calls", "expected"),
    [
        ("К00150", True, 5, ContactKind.CLIENT),
        # A code the catalogue does not know: undecided, because calling it a
        # customer would set a typo in stone.
        ("К028890", False, 5, ContactKind.UNKNOWN),
        # No code but the catalogue has the number — the catalogue supplies the
        # code; the employee simply never wrote it. Measured: 21 on one phone.
        (None, True, 5, ContactKind.CLIENT),
        # No code and nobody has ever called them.
        (None, False, 0, ContactKind.PERSONAL),
        (None, False, 3, ContactKind.UNKNOWN),
    ],
)
def test_suggest_kind(
    code: str | None, known: bool, calls: int, expected: ContactKind
) -> None:
    assert suggest_kind(code=code, known_in_catalogue=known, calls=calls) is expected


def test_nothing_is_auto_classified_a_customer_without_the_catalogue() -> None:
    """SALES SEAM: with ``known_in_catalogue`` always False, the chain never
    reaches ``CLIENT``. That is the conservative end of the rule, and an admin
    has to opt into the other one."""
    suggestions = {
        suggest_kind(code=code, known_in_catalogue=False, calls=calls)
        for code in (None, "К00150")
        for calls in (0, 7)
    }
    assert ContactKind.CLIENT not in suggestions


# ── The import modes ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "code", "in_catalogue", "expected"),
    [
        (ImportMode.ALL, None, False, True),
        (ImportMode.CODED, "К00150", False, True),
        (ImportMode.CODED, None, True, False),
        (ImportMode.KNOWN, None, True, True),
        (ImportMode.KNOWN, None, False, False),
    ],
)
def test_selected_by(
    mode: ImportMode, code: str | None, in_catalogue: bool, expected: bool
) -> None:
    assert selected_by(mode, code=code, in_catalogue=in_catalogue) is expected


# ── Reading a file ────────────────────────────────────────────


def test_a_cp1251_file_is_read() -> None:
    """⚠️ MANDATORY. Excel on Windows saves "CSV (разделители — запятые)" in
    cp1251, and the real list holds Cyrillic names. Read as UTF-8 the file
    either fails outright or the names turn to mojibake."""
    payload = "Ism,Telefon\nАзиз Ака Метан,+998901112233\n".encode("cp1251")
    rows = read_contacts_file(payload, filename="contacts.csv")
    assert rows[1][0] == "Азиз Ака Метан"


def test_a_semicolon_file_is_read() -> None:
    payload = b"Ism;Telefon\nAziz;+998901112233\nNodira;+998901112244\n"
    assert len(read_contacts_file(payload, filename="c.csv")) == 3


def test_a_workbook_is_refused_with_a_reason() -> None:
    """Not silently mis-read: the message names the one-click fix."""
    from src.core.errors import ValidationError

    with pytest.raises(ValidationError) as caught:
        read_contacts_file(b"PK\x03\x04", filename="contacts.xlsx")
    assert caught.value.detail == {
        "field": "file",
        "reason": "workbook_not_supported",
    }


def test_an_empty_file_is_refused() -> None:
    from src.core.errors import ValidationError

    with pytest.raises(ValidationError):
        read_contacts_file(b"", filename="contacts.csv")


def test_a_header_is_recognised() -> None:
    assert looks_like_header(("Ism", "Telefon"))
    assert not looks_like_header(("Aziz", "+998901112233"))


def test_every_phone_column_is_taken() -> None:
    """⚠️ Measured: in a 9,103-row file 70 rows carry a second number and 5 of
    those are CODED customers — exactly the valuable ones."""
    name, phones = header_columns(("Name", "Phone 1 - Value", "Phone 2 - Value"))
    assert name == 0
    assert phones == [1, 2]


def test_a_header_reading_nomer_is_not_taken_for_a_name() -> None:
    """Exact match for the name, prefix match for the phone — the other way
    round, "Nomer" looks like "nom"."""
    name, phones = header_columns(("Nomer", "Ism"))
    assert name == 1


def test_columns_are_found_by_content_when_the_header_does_not_help() -> None:
    rows = [("1", "Aziz Aka", "998901112233"), ("2", "Nodira", "998901112244")]
    name, phones = content_columns(rows, 3)
    assert name == 1
    assert phones == [2]


def test_a_row_number_column_is_not_taken_for_a_phone() -> None:
    """The threshold is seven digits and a row number is shorter."""
    rows = [("1", "Aziz", "998901112233"), ("2", "Nodira", "998901112244")]
    _, phones = content_columns(rows, 3)
    assert 0 not in phones


def test_a_single_column_file_is_refused() -> None:
    from src.core.errors import ValidationError

    with pytest.raises(ValidationError):
        pick_columns([("Aziz",), ("Nodira",)])


# ── Grouping the rows ─────────────────────────────────────────


def test_one_row_with_two_numbers_becomes_two_contacts() -> None:
    rows = [
        ("Name", "Phone 1 - Value", "Phone 2 - Value"),
        ("K00150 Elyor", "+998901112233", "+998901112244"),
    ]
    prepared = prepare_rows(rows)
    assert set(prepared.candidates) == {"901112233", "901112244"}
    for bucket in prepared.candidates.values():
        assert bucket[0].code == "К00150"


def test_one_number_under_several_names_keeps_them_all() -> None:
    """No choice is made here — the decision needs the catalogue."""
    rows = [
        ("Name", "Phone"),
        ("Asosiy Ombor", "+998951730700"),
        ("Конт Офес", "998951730700"),
    ]
    prepared = prepare_rows(rows)
    assert len(prepared.candidates["951730700"]) == 2
    assert prepared.duplicates == 1


def test_a_missing_number_and_a_bad_number_are_counted_apart() -> None:
    """⚠️ Measured: 7,316 rows with NO number against 11 with an unusable one.
    Adding them would read as "7,327 bad rows"."""
    rows = [
        ("Name", "Phone"),
        ("Aziz", ""),
        ("Nodira", "101"),
        ("Elyor", "+998901112233"),
    ]
    prepared = prepare_rows(rows)
    assert prepared.no_phone == 1
    assert prepared.bad_phone == 1
    assert prepared.read == 3
    assert set(prepared.candidates) == {"901112233"}


def test_a_nameless_row_is_counted_and_dropped() -> None:
    rows = [("Name", "Phone"), ("", "+998901112233")]
    prepared = prepare_rows(rows)
    assert prepared.no_name == 1
    assert prepared.candidates == {}


def test_a_number_shorter_than_nine_digits_is_never_a_key() -> None:
    """N37 — a short value matches the tail of almost any number, which is how
    strangers were once marked as colleagues."""
    assert parse_contact(name="Ombor", phone="700") is None


def test_the_key_is_the_last_nine_digits_in_every_format() -> None:
    for written in ("+998 90 111-22-33", "998901112233", "901112233", "8 90 111 22 33"):
        parsed = parse_contact(name="Aziz", phone=written)
        assert parsed is not None
        assert parsed.phone_key == "901112233", written
