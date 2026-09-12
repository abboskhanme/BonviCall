"""Self-declared number verification, and the setting that governs it.

═══ Why this exists ═══════════════════════════════════════════════════════
Until this revision a handset could only reach ``active`` two ways: the SIM
reported its own MSISDN (route 1), or the agent dialled a company receiver and
the caller ID matched (route 2). On this fleet route 1 is empty — Uzbek SIMs
do not populate ``getLine1Number()`` — and route 2 needs an always-on receiver
line that does not exist. A phone with a silent SIM and no receiver therefore
had **no path to activation at all**: it sat on E5 for ever, uploaded nothing,
and looked from the panel like a device that had never reported.

Admin attestation could rescue it, but only in principle: there was no
device-facing endpoint by which the phone could learn it had been attested and
collect its real token pair.

``self_declared`` is the third route. The agent redeems a single-use code that
an admin issued **for one specific number**, and — when
``enrolment.allow_self_declared`` is on — that is accepted as the binding. It
is the weakest of the three and is rendered as such everywhere the other two
are, exactly as ``admin_attested`` already is (SPEC §9.3): the identity anchor
degrades visibly or not at all.

The setting defaults to ``true`` because the alternative default is a fleet
that cannot enrol. Turning it off restores the previous behaviour with no code
change, which is the point of it being a setting.

``ALTER TYPE ... ADD VALUE`` is additive and irreversible — PostgreSQL has no
``DROP VALUE`` — so ``downgrade`` removes the settings row and leaves the enum
values, rather than lying about being able to remove them.

Revision ID: 006
Revises: 005
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The key seeded here, and its documented default. Same shape as the
#: baseline's ``SETTINGS`` table so ``test_every_declared_key_is_seeded`` finds
#: it in the database rather than in a second list somewhere.
SETTINGS: tuple[tuple[str, object, str, str], ...] = (
    (
        "enrolment.allow_self_declared",
        True,
        "bool",
        "Kod kiritilgan telefon o'z raqamini tasdiqlangan deb hisoblasinmi? "
        "O'chirilsa, raqam faqat SIM yoki qayta qo'ng'iroq orqali tasdiqlanadi.",
    ),
)

_settings_table = sa.table(
    "app_settings",
    sa.column("key", sa.String),
    sa.column("value", postgresql.JSONB),
    sa.column("value_type", sa.String),
    sa.column("description_uz", sa.Text),
)


def upgrade() -> None:
    # Written out literally rather than interpolated: the values belong in the
    # diff a reviewer reads, and ``test_migration_enum_table_matches_core_enums``
    # reads these statements to know what the database's enums hold.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE verification_method ADD VALUE IF NOT EXISTS 'self_declared'"
        )
        op.execute(
            "ALTER TYPE verification_state ADD VALUE IF NOT EXISTS 'self_declared'"
        )
        op.execute("ALTER TYPE funnel_stage ADD VALUE IF NOT EXISTS 'self_declared'")
        op.execute(
            "ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'installation_self_declared'"
        )

    op.bulk_insert(
        _settings_table,
        [
            {
                "key": key,
                "value": value,
                "value_type": value_type,
                "description_uz": description,
            }
            for key, value, value_type, description in SETTINGS
        ],
    )


def downgrade() -> None:
    """Remove the settings row; leave the enum values.

    PostgreSQL cannot remove an enum value, and removing one properly means
    recreating the type and rewriting ``installations``,
    ``number_verifications`` and every index over them. A downgrade that
    rewrote those tables to undo three additive values would cost far more than
    the values do. The settings row *can* go back, and does.
    """
    op.execute(
        sa.delete(_settings_table).where(
            _settings_table.c.key.in_([key for key, _, _, _ in SETTINGS])
        )
    )
