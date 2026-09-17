"""The contacts ORM model — one table (SPEC §3.8's kind of reference data).

Ported from BonviZvonki ``modules/clients/infrastructure/models.py``
(``ClientContactModel``). Its sibling there, ``ClientModel`` (the ``clients``
table), is **deliberately not ported** — see ``modules/clients/service.py``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base, TimestampMixin, UUIDMixin
from src.core.phone import PHONE_KEY_DIGITS


class ClientContactModel(Base, UUIDMixin, TimestampMixin):
    """A contact harvested from an employee's handset — the source of a code.

    ⚠️ THE KEY IS THE NUMBER, not the name. That is why ``phone_key`` is
    ``unique`` and why an upload OVERWRITES on it. The upstream provider's
    problem — three records for one number — is technically unrepresentable
    here (``rules.py`` records the measurement: 90 contacts imported twice
    became 270).

    ⚠️ Not merged into a customers table, and there is no customers table.
    BonviZvonki keeps a separate ``clients`` catalogue for sending Telegram
    surveys; this is a number→code dictionary and answers a different question.
    Merging the two would tie the survey flow to contact uploads. BonviCall has
    no survey flow at all (SPEC-ANALYTICS §0, phase 3), so only the dictionary
    half comes across.

    **No foreign key to ``calls`` or ``agents``, on purpose.** The join is the
    phone key, which is a value and not an identity: a contact exists before
    anybody has called the number and survives after the calls are gone, and
    ``calls.remote_number_key`` is NULL for anything shorter than 9 digits
    (N37). A foreign key would make the dictionary depend on traffic.
    """

    __tablename__ = "client_contacts"

    phone_key: Mapped[str] = mapped_column(
        sa.CHAR(PHONE_KEY_DIGITS),
        nullable=False,
        unique=True,
        index=True,
        doc=(
            "The last 9 digits — the one matching key in the product (N37). "
            "Written by the importer through core.phone.phone_key, the same "
            "function that generates calls.remote_number_key, so the two sides "
            "of every join are produced by one rule. NOT a generated column: "
            "the source number arrives in a file, is normalised once at import "
            "and is what makes the row exist at all."
        ),
    )
    code: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
        index=True,
        doc=(
            "The customer code read out of the contact name and transliterated "
            "to Cyrillic (contacts/rules.py). NULL — the name carried no code. "
            "Indexed because 'which other numbers carry this code' is asked "
            "once per contact card."
        ),
    )
    name: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc=(
            "The human name with the code cut out of it. NULL when the contact "
            "name was nothing but a code."
        ),
    )
    raw_name: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        doc=(
            "The name exactly as the handset had it — never edited. Kept so "
            "that 'why did this become that code?' is answerable from the row "
            "itself rather than by re-reading the file."
        ),
    )
    kind: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default=sa.text("'unknown'"),
        index=True,
        doc=(
            "A contacts.rules.ContactKind value: client | internal | personal "
            "| unknown. Stored as text rather than as a PostgreSQL enum, "
            "adopted from the source with its reason: adding a kind must not "
            "need an ALTER TYPE on a live database. The closed set is enforced "
            "at the wire boundary in schemas.py."
        ),
    )
    phone: Mapped[str | None] = mapped_column(
        sa.String(32),
        nullable=True,
        doc="The number as the file wrote it, for display. The key above is what matches.",
    )
    source_file: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        doc=(
            "Which upload produced this row. Not for undoing an import — for "
            "answering 'who added this line?'."
        ),
    )
