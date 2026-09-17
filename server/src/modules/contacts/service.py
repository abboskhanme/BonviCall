"""The contacts dictionary: list it, correct it, upload into it.

Ported from BonviZvonki ``modules/clients/application/contacts.py``
(``ContactDirectory``, ``build_preview``, ``import_contacts``) and the write
half of ``presentation/contacts_router.py``. The reading of the file itself is
``reader.py``; the rules it applies are ``rules.py``.

════════════════════════════════════════════════════════════════
 THE UPLOAD IS TWO STEPS, AND THAT IS THE POINT
════════════════════════════════════════════════════════════════

file -> **PREVIEW** -> the user confirms -> **WRITE**. Nothing changes in the
database until the second call. Deliberate: the contact list decides WHO a
customer is, and a wrong upload attaches conversations to the wrong code.

⚠️ BOTH STEPS READ FROM THE SAME FUNCTIONS (``_plan``). Written separately they
would drift, and the screen would promise "43 new" while 41 landed — a
difference nobody ever notices.

════════════════════════════════════════════════════════════════
 THE SALES SEAM
════════════════════════════════════════════════════════════════

BonviZvonki's version of this screen is *our phonebook beside the SAP partner
catalogue*: four match statuses, a "in SAP but in nobody's phone" list, a sales
summary on the card, and a default import mode meaning "only what SAP knows".
Every one of those reads ``src.modules.sales``.

**Nothing here does.** The partner catalogue arrives with that module. The
seam is one function — :meth:`ContactService._verified_codes` — which today
returns an empty set, and three call sites that already take it as a parameter
(``rules.choose_contact``, ``rules.resolve_code``, ``rules.suggest_kind``).
What the wire loses until then is listed in ``schemas.py``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import ErrorCode, NotFoundError, PayloadTooLargeError
from src.core.pagination import Cursor, Page, apply_keyset
from src.modules.clients.service import ClientDirectory
from src.modules.contacts.models import ClientContactModel
from src.modules.contacts.reader import Prepared, prepare_rows, read_contacts_file
from src.modules.contacts.rules import (
    ContactKind,
    ImportMode,
    choose_contact,
    resolve_code,
    selected_by,
    suggest_kind,
)

#: How many example rows the preview hands back. Returning the whole file would
#: stretch the response into megabytes for a screen that shows a sample.
SAMPLE_LIMIT = 200

#: Upload size limit. A contact list is tens of kilobytes; anything past this
#: means a different file was picked.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ContactRow:
    """One dictionary row, as the panel reads it."""

    __slots__ = (
        "calls",
        "code",
        "code_numbers",
        "kind",
        "name",
        "phone",
        "phone_key",
        "raw_name",
        "source_file",
    )

    def __init__(
        self,
        *,
        phone_key: str,
        phone: str | None,
        raw_name: str,
        name: str | None,
        code: str | None,
        kind: str,
        source_file: str | None = None,
        calls: int = 0,
        code_numbers: int = 1,
    ) -> None:
        self.phone_key = phone_key
        self.phone = phone
        self.raw_name = raw_name
        self.name = name
        self.code = code
        self.kind = kind
        self.source_file = source_file
        self.calls = calls
        """How many calls this number has. Filled where it is asked for: the
        preview counts them, the list does not — a per-row count over the whole
        table would make the list pay for a number the card shows better."""
        self.code_numbers = code_numbers
        """How many of OUR numbers carry this code.

        ⚠️ Two numbers for one customer is NOT an error, it is the ordinary
        case: the key is the number, so each number takes its own row and both
        lead to the same code. The partner catalogue records one number per
        code (measured: no exceptions), so the second number exists only in our
        list. Without showing this, the row looks like a duplicate."""


class ContactPreview:
    """What an upload WOULD do. Nothing is written."""

    def __init__(self, file: str) -> None:
        self.file = file
        self.read = 0
        self.parsed = 0
        self.no_phone = 0
        self.bad_phone = 0
        self.no_name = 0
        self.duplicates = 0
        self.with_code = 0
        self.created = 0
        self.updated = 0
        self.unchanged = 0
        self.calls_covered = 0
        self.suggested: dict[str, int] = {}
        self.would_import: dict[str, int] = {}
        """How many rows each mode would write — the user has to see the
        difference BEFORE choosing."""
        self.would_cover: dict[str, int] = {}
        """How many CALLS each mode would cover.

        ⚠️ A row count gives a false impression: "1,517 contacts" sounds like a
        lot and "611 contacts" sounds like a little. In fact those 611 cover a
        far larger share of the conversations, because customers are spoken to
        often and private acquaintances almost never. The decision is taken on
        this number."""
        self.rows: list[ContactRow] = []


class ContactImportReport:
    """What the upload DID."""

    def __init__(self, *, file: str, mode: ImportMode) -> None:
        self.file = file
        self.mode = mode.value
        self.read = 0
        self.created = 0
        self.updated = 0
        self.unchanged = 0
        self.no_phone = 0
        self.bad_phone = 0
        self.no_name = 0
        self.duplicates = 0
        self.skipped_filter = 0
        """Rows left out because of the mode that was chosen."""


class ContactService:
    """The dictionary. Owns ``client_contacts`` and the transaction on it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── The seam ──────────────────────────────────────────────

    async def _verified_codes(self, codes: set[str]) -> frozenset[str]:
        """Which of these codes the partner catalogue confirms.

        ⚠️ SALES SEAM. In the source this is a ``SELECT`` over
        ``sale_partners``; that table is being ported by another agent and
        **nothing in this module reads a ``sales*`` table**. Until it lands,
        nothing is confirmed.

        The empty set is the SAFE answer rather than a degraded one: the two
        rules that consult it — "a record whose code the catalogue confirms
        wins" and "a code glued to a word is accepted once confirmed" — are
        both rules that let a code OVERRIDE the ordinary decision, and the one
        real failure the source records (a warehouse line turned into a
        customer by a mistyped code) was caused by that override firing
        unconfirmed. With an empty set it cannot fire at all.
        """
        return frozenset()

    # ── Reading ───────────────────────────────────────────────

    def _filtered(
        self, statement: Select, *, kind: ContactKind | None, search: str | None
    ) -> Select:
        if kind is not None:
            statement = statement.where(ClientContactModel.kind == kind.value)
        if search:
            text = search.strip()
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            needle = f"%{escaped}%"
            conditions = [
                ClientContactModel.raw_name.ilike(needle, escape="\\"),
                ClientContactModel.name.ilike(needle, escape="\\"),
                ClientContactModel.code.ilike(needle, escape="\\"),
            ]
            digits = "".join(char for char in text if char.isdigit())
            if digits:
                conditions.append(ClientContactModel.phone_key.like(f"%{digits}%"))
            statement = statement.where(or_(*conditions))
        return statement

    async def page(
        self,
        *,
        kind: ContactKind | None = None,
        search: str | None = None,
        limit: int,
        cursor: Cursor | None = None,
        with_total: bool = False,
    ) -> Page[ContactRow]:
        """One keyset page of the dictionary, ordered by name.

        ⚠️ PAGED IN SQL, unlike the source. Theirs reads the WHOLE table and
        pages in Python, and its comment gives the reason: the match STATUS is
        not a column, it is computed in Python from two joins, so filtering on
        it in SQL would have produced a page that was filtered and a total that
        was not. With the partner catalogue deferred (SALES SEAM) there is no
        computed status left, every filter is a plain column predicate, and the
        page can be a real keyset page — which also means the list no longer
        loads thousands of rows to show fifty.
        """
        base = self._filtered(
            select(
                ClientContactModel.id,
                ClientContactModel.phone_key,
                ClientContactModel.phone,
                ClientContactModel.raw_name,
                ClientContactModel.name,
                ClientContactModel.code,
                ClientContactModel.kind,
                ClientContactModel.source_file,
            ),
            kind=kind,
            search=search,
        )

        total: int | None = None
        if with_total:
            total = int(
                (
                    await self.session.execute(
                        select(func.count()).select_from(base.subquery())
                    )
                ).scalar_one()
            )

        statement = apply_keyset(
            base,
            ClientContactModel.raw_name,
            ClientContactModel.id,
            cursor,
            descending=False,
        ).limit(limit + 1)
        rows = (await self.session.execute(statement)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        # ⚠️ "How many of our numbers carry this code" is counted over the
        # WHOLE table, not inside the page. Counted per page, a customer's
        # second number falling onto the next page would make the badge read
        # "1" and the duplicate would look like an error instead of the
        # ordinary case it is.
        per_code = await self.numbers_per_code({row.code for row in rows if row.code})
        items = [
            ContactRow(
                phone_key=row.phone_key,
                phone=row.phone,
                raw_name=row.raw_name,
                name=row.name,
                code=row.code,
                kind=row.kind,
                source_file=row.source_file,
                code_numbers=per_code.get(row.code, 1) if row.code else 1,
            )
            for row in rows
        ]
        next_cursor = (
            Cursor(sort_value=rows[-1].raw_name, row_id=rows[-1].id).encode()
            if has_more and rows
            else None
        )
        return Page(items=items, next_cursor=next_cursor, has_more=has_more, total=total)

    async def numbers_per_code(self, codes: set[str]) -> dict[str, int]:
        """Code -> how many numbers in the dictionary carry it."""
        if not codes:
            return {}
        rows = await self.session.execute(
            select(ClientContactModel.code, func.count().label("numbers"))
            .where(ClientContactModel.code.in_(codes))
            .group_by(ClientContactModel.code)
        )
        return {row.code: int(row.numbers) for row in rows}

    async def summary(self) -> dict[str, int]:
        """The header counts — by kind, plus the totals.

        ⚠️ Computed by the DATABASE in one grouped query, not by reading every
        row. The source computes it by running its own list function with a
        page size of a million, for the reason its comment gives: separate
        ``COUNT`` queries drifted from the list's logic and the header once said
        12 where the list showed 9. That risk is gone with the status filter
        (SALES SEAM), because there is no logic left to drift — a kind is a
        column, and the same column is what the list filters on.
        """
        rows = await self.session.execute(
            select(ClientContactModel.kind, func.count().label("rows")).group_by(
                ClientContactModel.kind
            )
        )
        counts = {f"kind:{row.kind}": int(row.rows) for row in rows}
        counts["total"] = sum(counts.values())
        counts["with_code"] = int(
            (
                await self.session.scalar(
                    select(func.count()).where(ClientContactModel.code.is_not(None))
                )
            )
            or 0
        )
        return counts

    async def get(self, phone_key: str) -> ContactRow | None:
        """One dictionary row, built the SAME way the list builds it.

        The row handed back after a correction has to match the row on screen;
        rebuilding it differently here would create two truths.
        """
        row = (
            await self.session.execute(
                select(
                    ClientContactModel.phone_key,
                    ClientContactModel.phone,
                    ClientContactModel.raw_name,
                    ClientContactModel.name,
                    ClientContactModel.code,
                    ClientContactModel.kind,
                    ClientContactModel.source_file,
                ).where(ClientContactModel.phone_key == phone_key)
            )
        ).first()
        if row is None:
            return None
        per_code = await self.numbers_per_code({row.code} if row.code else set())
        return ContactRow(
            phone_key=row.phone_key,
            phone=row.phone,
            raw_name=row.raw_name,
            name=row.name,
            code=row.code,
            kind=row.kind,
            source_file=row.source_file,
            code_numbers=per_code.get(row.code, 1) if row.code else 1,
        )

    async def other_numbers(self, code: str, *, except_key: str) -> list[ContactRow]:
        """The other numbers we hold under this code.

        ⚠️ Two numbers for one customer is the ordinary case and not an error;
        see ``rules.count_by_code``.
        """
        rows = await self.session.execute(
            select(
                ClientContactModel.phone_key,
                ClientContactModel.phone,
                ClientContactModel.raw_name,
                ClientContactModel.name,
                ClientContactModel.code,
                ClientContactModel.kind,
                ClientContactModel.source_file,
            )
            .where(
                ClientContactModel.code == code,
                ClientContactModel.phone_key != except_key,
            )
            .order_by(ClientContactModel.raw_name)
        )
        return [
            ContactRow(
                phone_key=row.phone_key,
                phone=row.phone,
                raw_name=row.raw_name,
                name=row.name,
                code=row.code,
                kind=row.kind,
                source_file=row.source_file,
            )
            for row in rows
        ]

    # ── Correcting by hand ────────────────────────────────────

    async def patch(
        self,
        phone_key: str,
        *,
        kind: ContactKind | None,
        code: str | None,
        name: str | None,
    ) -> ContactRow:
        """An admin's correction.

        ⚠️ The CODE is editable too. A code can be mistyped on the handset, and
        if fixing one meant re-uploading the whole file nobody would ever fix
        one.
        """
        contact = await self._require(phone_key)
        if kind is not None:
            contact.kind = kind.value
        if code is not None:
            contact.code = code.strip() or None
        if name is not None:
            contact.name = name.strip() or None
        await self.session.commit()
        row = await self.get(phone_key)
        if row is None:  # pragma: no cover - the row was just committed
            raise NotFoundError()
        return row

    async def delete(self, phone_key: str) -> None:
        """⚠️ Only the CONTACT goes. Calls are untouched — this list is a
        dictionary over them, never their source."""
        contact = await self._require(phone_key)
        await self.session.delete(contact)
        await self.session.commit()

    async def _require(self, phone_key: str) -> ClientContactModel:
        contact = await self.session.scalar(
            select(ClientContactModel).where(
                ClientContactModel.phone_key == phone_key
            )
        )
        if contact is None:
            raise NotFoundError()
        return contact

    # ── Uploading ─────────────────────────────────────────────

    async def _plan(
        self, payload: bytes, *, filename: str
    ) -> tuple[
        Prepared,
        list[Any],
        frozenset[str],
        dict[str, int],
        dict[str, ClientContactModel],
    ]:
        """Read the file and work out, for every number, what would be written.

        ⚠️ EVERY CANDIDATE'S CODE IS LOOKED UP FIRST, AND THE CHOICE COMES
        AFTER. The other way round, an unconfirmed code would win — which is
        exactly the warehouse-line failure ``rules.choose_contact`` records.
        (SALES SEAM: the lookup returns nothing today, so the choice falls
        through to "the most frequently written name", which is the safe half.)

        Both the preview and the write call this, so the screen and the
        database cannot disagree.
        """
        rows = read_contacts_file(payload, filename=filename)
        prepared = prepare_rows(rows)
        keys = set(prepared.candidates)

        verified = await self._verified_codes(_all_codes(prepared))
        chosen = [
            choose_contact(bucket, verified)
            for bucket in prepared.candidates.values()
        ]
        calls = await ClientDirectory(self.session).call_counts(keys)
        existing = await self._existing(keys)
        return prepared, chosen, verified, calls, existing

    async def preview(self, payload: bytes, *, filename: str) -> ContactPreview:
        """Read the file and say what would happen. WRITES NOTHING."""
        prepared, chosen, verified, calls, existing = await self._plan(
            payload, filename=filename
        )

        preview = ContactPreview(filename)
        _copy_counts(prepared, preview)
        preview.parsed = len(chosen)
        kinds: Counter[str] = Counter()
        would: Counter[str] = Counter()
        cover: Counter[str] = Counter()

        for contact in chosen:
            code, human = resolve_code(contact, verified)
            seen_calls = calls.get(contact.phone_key, 0)
            # SALES SEAM: `known_in_catalogue` is what the partner catalogue
            # would answer. Nothing is auto-classified `client` until it can.
            kind = suggest_kind(
                code=code, known_in_catalogue=False, calls=seen_calls
            )
            if code:
                preview.with_code += 1
            preview.calls_covered += seen_calls
            kinds[kind.value] += 1
            for option in ImportMode:
                if selected_by(option, code=code, in_catalogue=False):
                    would[option.value] += 1
                    cover[option.value] += seen_calls

            old = existing.get(contact.phone_key)
            if old is None:
                preview.created += 1
            elif _unchanged(old, code=code, name=human, raw_name=contact.raw_name):
                preview.unchanged += 1
            else:
                preview.updated += 1

            if len(preview.rows) < SAMPLE_LIMIT:
                preview.rows.append(
                    ContactRow(
                        phone_key=contact.phone_key,
                        phone=contact.phone,
                        raw_name=contact.raw_name,
                        name=human,
                        code=code,
                        # An existing row keeps the kind an admin gave it —
                        # the preview must show what WOULD be stored, and the
                        # writer does not overwrite it either.
                        kind=(old.kind if old else kind.value),
                        calls=seen_calls,
                    )
                )

        preview.suggested = dict(kinds)
        preview.would_import = {option.value: would[option.value] for option in ImportMode}
        preview.would_cover = {option.value: cover[option.value] for option in ImportMode}
        return preview

    async def import_contacts(
        self, payload: bytes, *, filename: str, mode: ImportMode
    ) -> ContactImportReport:
        """Write the list — upserting on the NUMBER.

        ⚠️ ``kind`` IS NOT CHANGED on an existing row. Once an admin has
        marked a contact "personal", re-uploading that phone must not turn it
        back into a customer — otherwise the private contacts would have to be
        separated again after every upload.
        """
        prepared, chosen, verified, calls, existing = await self._plan(
            payload, filename=filename
        )

        report = ContactImportReport(file=filename, mode=mode)
        _copy_counts(prepared, report)
        source = (filename or "")[:255] or None

        for contact in chosen:
            code, human = resolve_code(contact, verified)
            old = existing.get(contact.phone_key)

            # ⚠️ The mode never touches a row that already exists. A contact
            # taken once must not quietly go stale because a narrower mode was
            # chosen next time — it is already in the list and an admin has
            # looked at it.
            if old is None and not selected_by(mode, code=code, in_catalogue=False):
                report.skipped_filter += 1
                continue

            if old is None:
                kind = suggest_kind(
                    code=code, known_in_catalogue=False, calls=calls.get(contact.phone_key, 0)
                )
                self.session.add(
                    ClientContactModel(
                        phone_key=contact.phone_key,
                        code=code,
                        name=human,
                        raw_name=contact.raw_name,
                        phone=contact.phone,
                        kind=kind.value,
                        source_file=source,
                    )
                )
                report.created += 1
                continue

            if _unchanged(old, code=code, name=human, raw_name=contact.raw_name):
                report.unchanged += 1
                continue

            old.code = code
            old.name = human
            old.raw_name = contact.raw_name
            old.phone = contact.phone
            old.source_file = source
            report.updated += 1

        await self.session.commit()
        return report

    async def _existing(self, keys: set[str]) -> dict[str, ClientContactModel]:
        if not keys:
            return {}
        rows = await self.session.scalars(
            select(ClientContactModel).where(ClientContactModel.phone_key.in_(keys))
        )
        return {row.phone_key: row for row in rows}


def check_upload_size(size: int) -> None:
    """Refuse a file that is obviously not a contact list."""
    if size > MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            detail={"field": "file", "bytes": size, "limit": MAX_UPLOAD_BYTES},
        )


def _all_codes(prepared: Prepared) -> set[str]:
    """Every code the file offers — the clear ones and the glued candidates.

    Asked in ONE lookup: a second query for the candidates would be written
    with different conditions and the two would drift apart.
    """
    codes: set[str] = set()
    for bucket in prepared.candidates.values():
        for row in bucket:
            if row.code:
                codes.add(row.code)
            for code, _ in row.candidates:
                codes.add(code)
    return codes


def _unchanged(
    old: ClientContactModel, *, code: str | None, name: str | None, raw_name: str
) -> bool:
    return old.code == code and old.name == name and old.raw_name == raw_name


def _copy_counts(prepared: Prepared, target: Any) -> None:
    """The file-level tallies, onto whichever report is being built."""
    target.read = prepared.read
    target.no_phone = prepared.no_phone
    target.bad_phone = prepared.bad_phone
    target.no_name = prepared.no_name
    target.duplicates = prepared.duplicates


__all__ = [
    "MAX_UPLOAD_BYTES",
    "SAMPLE_LIMIT",
    "ContactImportReport",
    "ContactPreview",
    "ContactRow",
    "ContactService",
    "check_upload_size",
]
