"""Reference data reads (T49's directory half, T58's catalogue half).

The line directory is **assembled, not maintained**: the registered half is
computed from ``registered_numbers`` and only the admin's extras live in
``line_directory_entries``. Copying the registered numbers in here is how
BonviZvonki's directory starved — somebody had to remember to update it, and
10 of 33 employees had an entry (UC-25, L5).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ActorType, AppVariant, AuditAction
from src.core.errors import ConflictError, ErrorCode, NotFoundError
from src.modules.audit.service import AuditService
from src.modules.catalog.models import AppVersionModel, LineDirectoryEntryModel


class CatalogService:
    """Reads the product's reference tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def current_release(self, variant: AppVariant | None = None):
        """The published ``AppVersionModel`` row, or ``None``."""
        statement = select(AppVersionModel).where(
            AppVersionModel.is_current.is_(True),
            AppVersionModel.published_at.is_not(None),
        )
        if variant is not None:
            statement = statement.where(AppVersionModel.variant == variant)
        return await self.session.scalar(statement.limit(1))

    async def current_version_code(
        self, variant: AppVariant | None = None
    ) -> int | None:
        """The published build the install page hands out, or ``None``.

        ``None`` is a real answer before the first APK is uploaded, and the
        landing page says so in Uzbek rather than offering a dead button.
        """
        statement = select(AppVersionModel.version_code).where(
            AppVersionModel.is_current.is_(True),
            AppVersionModel.published_at.is_not(None),
        )
        if variant is not None:
            statement = statement.where(AppVersionModel.variant == variant)
        return await self.session.scalar(statement.limit(1))

    async def list_directory_entries(self):
        rows = list(
            (
                await self.session.scalars(
                    select(LineDirectoryEntryModel)
                    .where(LineDirectoryEntryModel.is_active.is_(True))
                    .order_by(LineDirectoryEntryModel.pattern)
                )
            ).all()
        )
        return rows, len(rows)

    async def add_directory_entry(self, payload, actor_id, ip):
        """Add a rule, then re-run the classification (T49).

        Both in one transaction: a directory that has changed and calls that
        have not is a report that contradicts the settings screen.
        """
        digits = "".join(c for c in payload.pattern if c.isdigit())
        if not digits:
            raise ConflictError(ErrorCode.BAD_REQUEST, detail={"field": "pattern"})
        existing = await self.session.scalar(
            select(LineDirectoryEntryModel).where(
                LineDirectoryEntryModel.pattern == digits,
                LineDirectoryEntryModel.kind == payload.kind,
            )
        )
        if existing is not None:
            existing.is_active = True
            entry = existing
        else:
            entry = LineDirectoryEntryModel(
                pattern=digits,
                kind=payload.kind,
                label=payload.label,
                created_by=actor_id,
            )
            self.session.add(entry)
        await self.session.flush()
        reclassified = await self._reclassify(actor_id, ip, digits, payload.kind.value)
        return entry, reclassified

    async def remove_directory_entry(self, entry_id, actor_id, ip):
        """Deactivate rather than delete: the audit trail needs the row."""
        entry = await self.session.get(LineDirectoryEntryModel, entry_id)
        if entry is None:
            raise NotFoundError()
        entry.is_active = False
        await self.session.flush()
        reclassified = await self._reclassify(actor_id, ip, entry.pattern, "removed")
        return entry, reclassified

    async def _reclassify(self, actor_id, ip, pattern: str, kind: str) -> int:
        from src.modules.calls.service import CallService

        changed = await CallService(self.session).reclassify()
        await AuditService(self.session).record(
            action=AuditAction.LINE_DIRECTORY_UPDATED,
            object_type="line_directory_entries",
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={"pattern": pattern, "kind": kind, "calls_reclassified": changed},
        )
        await self.session.commit()
        return changed

    async def directory_rules(self) -> tuple[tuple[str, str], ...]:
        """Active ``(kind, digits)`` pairs for the internal/external rule.

        Plain tuples rather than ORM rows: the caller is another module, and
        handing it entities from this table would let it write to them.
        """
        rows = (
            await self.session.execute(
                select(
                    LineDirectoryEntryModel.kind, LineDirectoryEntryModel.pattern
                ).where(LineDirectoryEntryModel.is_active.is_(True))
            )
        ).all()
        pairs = []
        for kind, pattern in rows:
            digits = "".join(character for character in pattern if character.isdigit())
            if digits:
                pairs.append((str(kind), digits))
        return tuple(pairs)
