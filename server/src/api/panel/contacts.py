"""The contacts dictionary for the panel — the handset phonebooks, centralised.

Ported from BonviZvonki ``modules/clients/presentation/contacts_router.py``.

═══ WHY IT IS A SEPARATE SECTION FROM /clients ═════════════════════════════
``/clients`` is assembled from calls and answers "who have we spoken to, and
how much". This answers a different question: what is this number called, does
it carry a customer code, and is it even a customer at all. Squeezing the two
onto one screen confuses both.

═══ ACCESS ═════════════════════════════════════════════════════════════════
``settings:read`` to read, ``settings:write`` to change. **No new permission
constant is introduced** (CONVENTIONS.md §11 item 3 — a constant added after
phase 1 is a review failure).

The source uses ``clients:read`` / ``clients:write``, which do not exist here.
The nearest existing pair is the one already guarding the OTHER number→meaning
dictionary in this product: ``api/panel/catalog.py`` gates the line directory
(``line_directory_entries``, UC-25) on exactly ``settings:read`` /
``settings:write``. This table is the same kind of thing — admin-maintained
reference data, keyed by phone number, that changes what the reports say — so
it takes the same gate, and the split lands where the source's own comment puts
it: **read for admin and manager, write for the admin only**, because editing
the contact list decides who a customer is and therefore changes the numbers in
every report. ``settings:read`` is held by admin and manager; ``settings:write``
by the admin alone.

⚠️ NOT ``calls:read``. A salesperson holds ``calls:read:own`` and this list is
fleet-wide by shape — it is every employee's phonebook — so own-scope has
nothing to narrow on and would have to be invented.

═══ NOT HERE ══════════════════════════════════════════════════════════════
The SAP partner catalogue half of this screen — the right-hand column, the
four match statuses, the "in the catalogue but in nobody's phone" list and the
sales summary on the card. The ``sales`` module is being ported separately;
nothing in this file creates, reads or references a ``sales*`` table.
``modules/contacts/schemas.py`` lists every field that waits on it.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from src.core.deps import SessionDep
from src.core.errors import BadRequestError, ErrorCode, NotFoundError
from src.core.pagination import Cursor, clamp_limit
from src.core.permissions import Perm, require_permission
from src.modules.clients.rules import is_client_key
from src.modules.clients.service import ClientDirectory
from src.modules.contacts.rules import DEFAULT_IMPORT_MODE, ContactKind, ImportMode
from src.modules.contacts.schemas import (
    ContactCallsBrief,
    ContactDetailResponse,
    ContactImportResponse,
    ContactPageResponse,
    ContactPatchRequest,
    ContactPreviewResponse,
    ContactRowOut,
    ContactSummaryResponse,
)
from src.modules.contacts.service import ContactService, check_upload_size

router = APIRouter(prefix="/contacts", tags=["Contacts"])

_read = require_permission(Perm.SETTINGS_READ)
_write = require_permission(Perm.SETTINGS_WRITE)


def _row(row) -> ContactRowOut:
    return ContactRowOut(
        phone_key=row.phone_key,
        phone=row.phone,
        raw_name=row.raw_name,
        name=row.name,
        code=row.code,
        kind=ContactKind(row.kind),
        source_file=row.source_file,
        calls=row.calls,
        code_numbers=row.code_numbers,
    )


def _key(raw: str) -> str:
    """The path segment as a phone key — digits only, nine of them."""
    if not is_client_key(raw):
        raise BadRequestError(ErrorCode.BAD_REQUEST, detail={"field": "phone_key"})
    return raw.strip()


async def _payload(file: UploadFile) -> tuple[str, bytes]:
    data = await file.read()
    check_upload_size(len(data))
    return file.filename or "contacts.csv", data


@router.get("", response_model=ContactPageResponse, dependencies=[Depends(_read)])
async def list_contacts(
    session: SessionDep,
    kind: Annotated[ContactKind | None, Query()] = None,
    search: Annotated[
        str | None, Query(max_length=100, description="Name, code or number.")
    ] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query()] = None,
    with_total: Annotated[bool, Query()] = False,
) -> ContactPageResponse:
    """The dictionary, ordered by the name the handset had."""
    page = await ContactService(session).page(
        kind=kind,
        search=search,
        limit=clamp_limit(limit),
        cursor=Cursor.decode(cursor) if cursor else None,
        with_total=with_total,
    )
    return ContactPageResponse(
        items=[_row(row) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        total=page.total,
    )


@router.get(
    "/summary", response_model=ContactSummaryResponse, dependencies=[Depends(_read)]
)
async def contacts_summary(session: SessionDep) -> ContactSummaryResponse:
    """The header counts, by kind.

    ⚠️ Declared ABOVE ``/{phone_key}`` so the literal path stays above the
    parameterised one. The two do not collide under FastAPI's ordered matching,
    but keeping the literal first is the habit that stops them colliding the
    day somebody renames a path.
    """
    counts = await ContactService(session).summary()
    return ContactSummaryResponse(
        total=counts.get("total", 0),
        with_code=counts.get("with_code", 0),
        by_kind={
            kind.value: counts.get(f"kind:{kind.value}", 0) for kind in ContactKind
        },
    )


@router.post(
    "/import/preview",
    response_model=ContactPreviewResponse,
    dependencies=[Depends(_write)],
)
async def preview_import(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="A `.csv` or `.tsv` export.")],
) -> ContactPreviewResponse:
    """Read the file and say what WOULD happen. Writes nothing.

    The steps are: file -> this -> the user confirms -> the SAME file goes to
    ``POST /contacts/import``. Both read from one function, so the screen and
    the database cannot promise different numbers.

    ⚠️ Gated on ``settings:write`` even though it writes nothing: it reads an
    uploaded file and reports what is in every employee's phonebook, which is
    not something the read gate was granted for.
    """
    name, data = await _payload(file)
    preview = await ContactService(session).preview(data, filename=name)
    return ContactPreviewResponse(
        file=preview.file,
        read=preview.read,
        parsed=preview.parsed,
        no_phone=preview.no_phone,
        bad_phone=preview.bad_phone,
        no_name=preview.no_name,
        duplicates=preview.duplicates,
        with_code=preview.with_code,
        created=preview.created,
        updated=preview.updated,
        unchanged=preview.unchanged,
        calls_covered=preview.calls_covered,
        suggested=preview.suggested,
        would_import=preview.would_import,
        would_cover=preview.would_cover,
        rows=[_row(row) for row in preview.rows],
    )


@router.post(
    "/import", response_model=ContactImportResponse, dependencies=[Depends(_write)]
)
async def import_contacts(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="A `.csv` or `.tsv` export.")],
    mode: Annotated[
        ImportMode,
        Query(
            description=(
                "coded — only the rows with a code in the name (default); "
                "known — code or partner catalogue; all — everything."
            )
        ),
    ] = DEFAULT_IMPORT_MODE,
) -> ContactImportResponse:
    """Write the list, upserting on the NUMBER.

    ⚠️ The default is the NARROW mode. What gets uploaded is a full export of
    somebody's phone, private contacts included; if the default were
    "everything", strangers' names would land in the database on the very first
    upload and getting them out again is hard.

    ⚠️ BonviZvonki recomputes every call's stored customer code here, in the
    same request. **That step does not exist in BonviCall and must not be
    added**: there is no ``calls.client_code`` column to recompute — SPEC
    §3.5's table has none and SPEC-ANALYTICS §0 rule 1 forbids adding one — and
    the directory resolves the name and code at read time from this table,
    which is what makes the phones uploadable one at a time with nothing to
    press afterwards. The source stores the value because it joins 84,692 calls
    against 12,349 sales rows; there is no such join here.
    """
    name, data = await _payload(file)
    report = await ContactService(session).import_contacts(
        data, filename=name, mode=mode
    )
    return ContactImportResponse(
        file=report.file,
        mode=ImportMode(report.mode),
        read=report.read,
        created=report.created,
        updated=report.updated,
        unchanged=report.unchanged,
        no_phone=report.no_phone,
        bad_phone=report.bad_phone,
        no_name=report.no_name,
        duplicates=report.duplicates,
        skipped_filter=report.skipped_filter,
    )


@router.get(
    "/{phone_key}", response_model=ContactDetailResponse, dependencies=[Depends(_read)]
)
async def contact_detail(session: SessionDep, phone_key: str) -> ContactDetailResponse:
    """Everything known about one number.

    ⚠️ Opened by NUMBER only. The source also accepts a code, because some of
    its rows come from the partner catalogue alone and a few of those have no
    phone number at all — clicking one would otherwise open nothing. Every row
    here has a number by construction (it is the primary key of the
    dictionary), so the second door has nothing behind it. It returns with the
    ``sales`` module, and with the rows that need it.
    """
    key = _key(phone_key)
    service = ContactService(session)
    contact = await service.get(key)
    if contact is None:
        raise NotFoundError()

    other = await service.other_numbers(contact.code, except_key=key) if contact.code else []
    brief = await ClientDirectory(session).brief(key)
    return ContactDetailResponse(
        phone_key=key,
        contact=_row(contact),
        other_numbers=[_row(row) for row in other],
        calls=(
            None
            if brief is None
            else ContactCallsBrief(
                calls_total=brief.calls_total,
                inbound=brief.inbound,
                outbound=brief.outbound,
                missed=brief.missed,
                talk_seconds=brief.talk_seconds,
                first_call_at=(
                    brief.first_call_at.isoformat() if brief.first_call_at else None
                ),
                last_call_at=(
                    brief.last_call_at.isoformat() if brief.last_call_at else None
                ),
                agent_count=brief.agent_count,
                main_agent_name=brief.main_agent_name,
            )
        ),
    )


@router.patch(
    "/{phone_key}", response_model=ContactRowOut, dependencies=[Depends(_write)]
)
async def patch_contact(
    session: SessionDep, phone_key: str, payload: ContactPatchRequest
) -> ContactRowOut:
    """Correct a contact's kind, code or name by hand."""
    row = await ContactService(session).patch(
        _key(phone_key),
        kind=payload.kind,
        code=payload.code,
        name=payload.name,
    )
    return _row(row)


@router.delete(
    "/{phone_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    dependencies=[Depends(_write)],
)
async def delete_contact(session: SessionDep, phone_key: str) -> Response:
    """⚠️ Only the CONTACT is removed. Calls are untouched — this list is a
    dictionary over them, never their source."""
    await ContactService(session).delete(_key(phone_key))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
