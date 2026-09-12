"""Reading settings (SPEC §3.8).

Every threshold in the product is a row in ``app_settings``, seeded by the
migration with its documented default. Nothing hard-codes one: a threshold that
is not a row here is a threshold nobody can change without a deploy.

This is the **read** half. The admin-facing write API, the retention
confirmation gate and ``core/settings_keys.py`` belong to T58; a missing key
raises rather than defaulting silently, because SPEC §3.8's whole point is that
a missing key is a bug and not a silent ``None``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ActorType, AuditAction
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.core.settings_keys import ALL_SETTING_KEYS, DEVICE_VISIBLE_KEYS, SettingKey
from src.modules.audit.service import AuditService
from src.modules.settings.models import AppSettingModel


class SettingsService:
    """Typed reads of ``app_settings``. Caches nothing — the table is 28 rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> Any:
        value = await self.session.scalar(
            select(AppSettingModel.value).where(AppSettingModel.key == key)
        )
        if value is None:
            raise KeyError(
                f"setting {key!r} is missing. Every key in SPEC §3.8 is seeded by "
                "the migration, so this means the seed did not run."
            )
        return value

    async def get_int(self, key: str) -> int:
        return int(await self.get(key))

    async def get_str(self, key: str) -> str:
        return str(await self.get(key))

    async def get_bool(self, key: str) -> bool:
        """A JSONB ``true``/``false``.

        ``bool()`` of the raw value rather than a string comparison: the column
        is JSONB, so a boolean setting arrives as a Python ``bool`` and the
        string ``"false"`` — which is truthy — is not a value this column can
        hold.
        """
        return bool(await self.get(key))

    async def get_list(self, key: str) -> list[Any]:
        value = await self.get(key)
        return list(value) if isinstance(value, list) else [value]

    # --- Panel administration (T58) ---------------------------------------

    async def list(self) -> tuple[list[AppSettingModel], int]:
        rows = list(
            (
                await self.session.scalars(
                    select(AppSettingModel).order_by(AppSettingModel.key)
                )
            ).all()
        )
        return rows, len(rows)

    async def device_config(self) -> dict[str, Any]:
        """The subset a phone is told (``DEVICE_VISIBLE_KEYS``).

        A handset has no business knowing the retention period or who receives
        the alert e-mails, so the block is an allow-list rather than a dump.
        """
        rows = (
            await self.session.execute(
                select(AppSettingModel.key, AppSettingModel.value).where(
                    AppSettingModel.key.in_(DEVICE_VISIBLE_KEYS)
                )
            )
        ).all()
        return {key: value for key, value in rows}

    async def update(
        self, key: str, value: Any, confirm: bool, actor_id: uuid.UUID, ip: str | None
    ) -> AppSettingModel:
        """Change one setting, with the one confirmation gate SPEC §3.11 names.

        Lowering ``retention.audio_months`` below
        ``retention.confirm_below_months`` deletes recordings that still exist,
        so it is refused with 409 unless the caller says so explicitly. Every
        other setting is an ordinary write.
        """
        if key not in ALL_SETTING_KEYS:
            raise NotFoundError()
        row = await self.session.get(AppSettingModel, key)
        if row is None:
            raise NotFoundError()

        destructive = key == SettingKey.RETENTION_AUDIO_MONTHS
        if destructive:
            floor = await self.get_int(SettingKey.RETENTION_CONFIRM_BELOW_MONTHS)
            if int(value) < floor and not confirm:
                raise ConflictError(
                    ErrorCode.RETENTION_CONFIRMATION_REQUIRED,
                    detail={"confirm_below_months": floor, "requested": int(value)},
                )

        previous = row.value
        row.value = value
        row.updated_by = actor_id
        await AuditService(self.session).record(
            # Retention is technically a setting, but it is the one whose
            # change destroys data — "who shortened retention, and when" must
            # be one filter, not a JSONB dig through every settings change.
            action=(
                AuditAction.RETENTION_CHANGED
                if destructive
                else AuditAction.SETTING_UPDATED
            ),
            object_type="app_settings",
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"key": key, "from": previous, "to": value},
        )
        await self.session.commit()
        # ``updated_at`` has a server-side ``onupdate``, so its new value is
        # only known after the UPDATE. Without this refresh, serialising the
        # row triggers lazy IO outside the async greenlet and 500s.
        await self.session.refresh(row)
        return row
