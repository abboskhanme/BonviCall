"""The contacts dictionary over the wire: access, the two-step upload, edits.

The three things that can make this screen do damage, and therefore the three
things asserted hardest:

  · a preview that writes something;
  · a re-upload that undoes an admin's classification, so the private contacts
    have to be separated again after every import;
  · a wide import mode reached by accident, which puts strangers' names into
    the company's database on the first upload.
"""

from __future__ import annotations

import pytest

from src.core.enums import CallDirection, CallDisposition
from src.modules.contacts.models import ClientContactModel

pytestmark = pytest.mark.asyncio

CONTACTS = "/api/v1/contacts"
KEY = "901112233"

#: A two-column export with a header, which is the ordinary shape.
CSV = b"Ism,Telefon\nK00150 Elyor aka,+998901112233\nShifokor,+998907778899\n"


def _file(payload: bytes = CSV, name: str = "contacts.csv") -> dict:
    return {"file": (name, payload, "text/csv")}


async def _contact(db, **overrides) -> ClientContactModel:
    values = {
        "phone_key": KEY,
        "code": "К00150",
        "name": "Elyor aka",
        "raw_name": "K00150 Elyor aka",
        "kind": "client",
    }
    values.update(overrides)
    contact = ClientContactModel(**values)
    db.add(contact)
    await db.flush()
    return contact


# ── Access ────────────────────────────────────────────────────


async def test_anonymous_is_401(client) -> None:
    assert (await client.get(CONTACTS)).status_code == 401
    assert (await client.get(f"{CONTACTS}/summary")).status_code == 401
    assert (await client.post(f"{CONTACTS}/import", files=_file())).status_code == 401


async def test_a_salesperson_may_not_read_the_dictionary(sales) -> None:
    """This list is every employee's phonebook — fleet-wide by shape, so
    own-scope has nothing to narrow on and would have to be invented."""
    assert (await sales.get(CONTACTS)).status_code == 403


async def test_a_manager_may_read_but_not_write(manager, db) -> None:
    """The split the source's own comment puts here: editing the contact list
    decides who a customer is, and therefore changes the numbers in every
    report."""
    await _contact(db)
    assert (await manager.get(CONTACTS)).status_code == 200
    assert (await manager.get(f"{CONTACTS}/summary")).status_code == 200
    assert (
        await manager.patch(f"{CONTACTS}/{KEY}", json={"kind": "personal"})
    ).status_code == 403
    assert (await manager.delete(f"{CONTACTS}/{KEY}")).status_code == 403
    assert (
        await manager.post(f"{CONTACTS}/import", files=_file())
    ).status_code == 403
    assert (
        await manager.post(f"{CONTACTS}/import/preview", files=_file())
    ).status_code == 403


async def test_an_admin_may_write(admin, db) -> None:
    await _contact(db)
    assert (
        await admin.patch(f"{CONTACTS}/{KEY}", json={"kind": "personal"})
    ).status_code == 200


# ── The list ──────────────────────────────────────────────────


async def test_the_list_returns_the_dictionary(manager, db) -> None:
    await _contact(db)
    body = (await manager.get(CONTACTS, params={"with_total": "true"})).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["phone_key"] == KEY
    assert row["code"] == "К00150"
    assert row["raw_name"] == "K00150 Elyor aka"
    assert row["kind"] == "client"


async def test_the_list_filters_by_kind(manager, db) -> None:
    await _contact(db)
    await _contact(db, phone_key="907778899", code=None, kind="personal", raw_name="Shifokor")
    body = (await manager.get(CONTACTS, params={"kind": "personal"})).json()
    assert [row["phone_key"] for row in body["items"]] == ["907778899"]


async def test_the_list_searches_name_code_and_number(manager, db) -> None:
    await _contact(db)
    for term in ("elyor", "К00150", "90 111"):
        body = (await manager.get(CONTACTS, params={"search": term})).json()
        assert [row["phone_key"] for row in body["items"]] == [KEY], term


async def test_two_numbers_under_one_code_are_counted_across_the_whole_table(
    manager, db
) -> None:
    """⚠️ Counted BEFORE the page, not inside it. Counted per page, a
    customer's second number falling onto the next page would make the badge
    read "1" and the duplicate would look like an error instead of the ordinary
    case it is."""
    await _contact(db)
    await _contact(db, phone_key="907778899", raw_name="K00150 Elyor ikkinchi")

    body = (await manager.get(CONTACTS, params={"limit": "1"})).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["code_numbers"] == 2


async def test_the_summary_counts_by_kind(manager, db) -> None:
    await _contact(db)
    await _contact(db, phone_key="907778899", code=None, kind="personal", raw_name="Shifokor")
    body = (await manager.get(f"{CONTACTS}/summary")).json()
    assert body["total"] == 2
    assert body["with_code"] == 1
    assert body["by_kind"]["client"] == 1
    assert body["by_kind"]["personal"] == 1
    assert body["by_kind"]["internal"] == 0, "an absent kind is 0, never missing"


# ── The card ──────────────────────────────────────────────────


async def test_an_unknown_number_is_404(manager) -> None:
    assert (await manager.get(f"{CONTACTS}/900000000")).status_code == 404


async def test_a_key_that_is_not_digits_is_400(manager) -> None:
    assert (await manager.get(f"{CONTACTS}/undefined")).status_code == 400


async def test_the_card_shows_this_number_s_traffic(
    manager, db, call_factory, installation_factory
) -> None:
    await _contact(db)
    installation = await installation_factory()
    await call_factory(installation=installation, remote_number="+998901112233")
    await call_factory(
        installation=installation,
        remote_number="901112233",
        direction=CallDirection.INCOMING,
        disposition=CallDisposition.MISSED,
    )

    body = (await manager.get(f"{CONTACTS}/{KEY}")).json()
    assert body["calls"]["calls_total"] == 2
    assert body["calls"]["missed"] == 1


async def test_the_card_of_a_number_nobody_has_called_has_no_traffic(
    manager, db
) -> None:
    """Null, not zeros: "nobody has ever called this number" is a different
    statement from "they called and we counted nothing"."""
    await _contact(db)
    body = (await manager.get(f"{CONTACTS}/{KEY}")).json()
    assert body["calls"] is None


async def test_the_card_lists_our_other_numbers_under_the_same_code(
    manager, db
) -> None:
    await _contact(db)
    await _contact(db, phone_key="907778899", raw_name="K00150 Elyor ikkinchi")
    body = (await manager.get(f"{CONTACTS}/{KEY}")).json()
    assert [row["phone_key"] for row in body["other_numbers"]] == ["907778899"]


# ── Correcting by hand ────────────────────────────────────────


async def test_an_admin_can_correct_the_code(admin, db) -> None:
    """A code can be mistyped on the handset, and if fixing one meant
    re-uploading the whole file nobody would ever fix one."""
    await _contact(db, code="К028890")
    body = (await admin.patch(f"{CONTACTS}/{KEY}", json={"code": "К02889"})).json()
    assert body["code"] == "К02889"


async def test_deleting_a_contact_leaves_the_calls_alone(
    admin, db, call_factory, installation_factory
) -> None:
    """⚠️ This list is a dictionary OVER the calls, never their source."""
    await _contact(db)
    installation = await installation_factory()
    await call_factory(installation=installation, remote_number="+998901112233")

    assert (await admin.delete(f"{CONTACTS}/{KEY}")).status_code == 204
    assert (await admin.get(f"{CONTACTS}/{KEY}")).status_code == 404

    body = (await admin.get("/api/v1/clients", params={"search": "90 111"})).json()
    assert body["items"][0]["calls_total"] == 1


async def test_deleting_an_unknown_contact_is_404(admin) -> None:
    assert (await admin.delete(f"{CONTACTS}/900000000")).status_code == 404


# ── The upload ────────────────────────────────────────────────


async def test_a_preview_writes_nothing(admin) -> None:
    """The whole reason the upload is two steps."""
    body = (await admin.post(f"{CONTACTS}/import/preview", files=_file())).json()
    assert body["parsed"] == 2
    assert body["created"] == 2
    assert (await admin.get(CONTACTS, params={"with_total": "true"})).json()["total"] == 0


async def test_the_preview_and_the_write_agree(admin) -> None:
    """⚠️ Both read from one function. Written separately they drift, and the
    screen promises "43 new" while 41 land — a difference nobody notices."""
    preview = (await admin.post(f"{CONTACTS}/import/preview", files=_file())).json()
    report = (
        await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    ).json()
    assert report["created"] == preview["would_import"]["all"]


async def test_the_default_mode_takes_only_the_coded_rows(admin) -> None:
    """⚠️ What gets uploaded is a full export of somebody's phone, private
    contacts included. If the default were "everything", strangers' names would
    land in the database on the very first upload."""
    report = (await admin.post(f"{CONTACTS}/import", files=_file())).json()
    assert report["created"] == 1
    assert report["skipped_filter"] == 1

    body = (await admin.get(CONTACTS)).json()
    assert [row["phone_key"] for row in body["items"]] == [KEY]
    assert body["items"][0]["code"] == "К00150"
    assert body["items"][0]["name"] == "Elyor aka", "the code is cut out of the name"


async def test_the_wide_mode_takes_everything(admin) -> None:
    report = (
        await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    ).json()
    assert report["created"] == 2
    assert report["skipped_filter"] == 0


async def test_re_uploading_the_same_file_changes_nothing(admin) -> None:
    """The key is the NUMBER and the write is an upsert on it — the duplicate
    explosion the source records (90 contacts becoming 270) cannot happen."""
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    report = (
        await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    ).json()
    assert report["created"] == 0
    assert report["unchanged"] == 2
    assert (await admin.get(CONTACTS, params={"with_total": "true"})).json()["total"] == 2


async def test_a_re_upload_never_undoes_an_admin_s_classification(admin) -> None:
    """⚠️ Once somebody has marked a contact "personal", re-uploading that
    phone must not turn it back into a customer — otherwise the private
    contacts have to be separated again after every import."""
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    await admin.patch(f"{CONTACTS}/{KEY}", json={"kind": "personal"})
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    body = (await admin.get(f"{CONTACTS}/{KEY}")).json()
    assert body["contact"]["kind"] == "personal"


async def test_a_narrower_mode_does_not_drop_a_row_already_taken(admin) -> None:
    """⚠️ The mode never touches a row that already exists: a contact taken
    once must not quietly go stale because a narrower mode was chosen next
    time."""
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    report = (
        await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "coded"})
    ).json()
    assert report["skipped_filter"] == 0
    assert report["unchanged"] == 2


async def test_an_edited_name_is_overwritten_by_the_next_upload(admin) -> None:
    """The handset's list is the source of the NAME; only ``kind`` is the
    admin's. Stated by a test so the asymmetry is deliberate rather than
    accidental."""
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    await admin.patch(f"{CONTACTS}/{KEY}", json={"name": "Boshqa nom"})
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    body = (await admin.get(f"{CONTACTS}/{KEY}")).json()
    assert body["contact"]["name"] == "Elyor aka"


async def test_the_preview_counts_what_each_mode_would_cover(
    admin, call_factory, installation_factory
) -> None:
    """⚠️ A row count flatters the wide mode. The decision is taken on the
    CALLS covered: the narrow set is spoken to far more often."""
    installation = await installation_factory()
    for _ in range(4):
        await call_factory(installation=installation, remote_number="+998901112233")
    await call_factory(installation=installation, remote_number="+998907778899")

    body = (await admin.post(f"{CONTACTS}/import/preview", files=_file())).json()
    assert body["calls_covered"] == 5
    assert body["would_cover"]["coded"] == 4
    assert body["would_cover"]["all"] == 5


async def test_the_preview_counts_missing_and_bad_numbers_apart(admin) -> None:
    """⚠️ Measured: 7,316 rows with NO number against 11 with an unusable one.
    Added together they read as "7,327 bad rows"."""
    payload = b"Ism,Telefon\nAziz,\nNodira,101\nK00150 Elyor,+998901112233\n"
    body = (await admin.post(f"{CONTACTS}/import/preview", files=_file(payload))).json()
    assert body["no_phone"] == 1
    assert body["bad_phone"] == 1
    assert body["parsed"] == 1


async def test_a_workbook_upload_is_refused(admin) -> None:
    response = await admin.post(
        f"{CONTACTS}/import/preview", files=_file(b"PK\x03\x04", "contacts.xlsx")
    )
    assert response.status_code == 422
    assert response.json()["error"]["detail"]["reason"] == "workbook_not_supported"


async def test_an_empty_file_is_refused(admin) -> None:
    assert (
        await admin.post(f"{CONTACTS}/import/preview", files=_file(b""))
    ).status_code == 422


async def test_nothing_is_auto_classified_a_customer(admin) -> None:
    """SALES SEAM: with no partner catalogue to confirm a code,
    ``suggest_kind`` never reaches ``client`` — the conservative end of the
    rule, which an admin then opts out of by hand."""
    await admin.post(f"{CONTACTS}/import", files=_file(), params={"mode": "all"})
    body = (await admin.get(CONTACTS)).json()
    kinds = {row["phone_key"]: row["kind"] for row in body["items"]}
    # A code the catalogue cannot confirm stays UNDECIDED: marking it
    # "customer" would set a possible typo in stone.
    assert kinds[KEY] == "unknown"
    # No code and nobody has ever called them — most likely a private
    # acquaintance, and an admin is the one who decides.
    assert kinds["907778899"] == "personal"
    assert "client" not in set(kinds.values())
