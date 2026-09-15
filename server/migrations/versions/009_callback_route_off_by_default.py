"""Switch off the callback verification route by default.

The route (SPEC §9.4) proves a number by having the handset dial a receiver on
a known line and reading the caller id. It is the strongest proof of a number
this product has — and no deployment of it has ever had a receiver. The result
was a rollout page that led with a red "nobody can enrol" banner about
infrastructure that does not exist, while handsets enrolled perfectly well
through the SIM, an admin's attestation, or the code alone.

A banner that is always red is a banner nobody reads, and the day a real
receiver goes down it would say exactly what it had been saying for months.

**Nothing is deleted.** The endpoints, the tables and the screens all stay;
``enrolment.callback_enabled`` decides whether they are offered. A fleet that
installs a receiver turns the route back on with one row rather than a release,
which is the whole reason this is a setting and not a code change.

Revision ID: 009
Revises: 008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The key seeded here, and its documented default. Same shape as the
#: baseline's ``SETTINGS`` table so ``test_every_declared_key_is_seeded`` finds
#: it in the database rather than in a second list somewhere.
SETTINGS: tuple[tuple[str, object, str, str], ...] = (
    (
        "enrolment.callback_enabled",
        False,
        "bool",
        "Raqamni qayta qo'ng'iroq orqali tasdiqlash ishlatiladimi? Buning "
        "uchun ma'lum raqamdagi qabul qiluvchi qurilma kerak. O'chirilgan "
        "bo'lsa, raqam SIM, administrator tasdig'i yoki kod orqali "
        "biriktiriladi.",
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
    op.execute(
        sa.delete(_settings_table).where(
            _settings_table.c.key.in_([key for key, _, _, _ in SETTINGS])
        )
    )
