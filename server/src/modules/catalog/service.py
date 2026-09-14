"""Reference data reads (T49's directory half, T58's catalogue half).

The line directory is **assembled, not maintained**: the registered half is
computed from ``registered_numbers`` and only the admin's extras live in
``line_directory_entries``. Copying the registered numbers in here is how
BonviZvonki's directory starved — somebody had to remember to update it, and
10 of 33 employees had an entry (UC-25, L5).
"""

from __future__ import annotations

import uuid
from typing import IO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.core.config import get_settings
from src.core.enums import ActorType, AppVariant, AuditAction
from src.core.errors import ConflictError, ErrorCode, NotFoundError, ValidationError
from src.core.logging import get_logger
from src.core.storage import LocalFsReleaseStore
from src.modules.audit.service import AuditService
from src.modules.catalog.models import AppVersionModel, LineDirectoryEntryModel
from src.modules.catalog.rules import (
    ApkInspection,
    inspect_apk,
    normalise_fingerprint,
)
from src.modules.catalog.schemas import AppVersionResponse, UploadReleaseRequest
from src.modules.users.models import UserModel

log = get_logger(__name__)


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

    async def published_releases(self) -> list[AppVersionModel]:
        """The current build of every variant, newest variant order aside.

        What the public download page reads. It asks for the *published*
        current row per variant, so an uploaded-but-not-published build is
        invisible here exactly as it is to every phone — the two-step upload
        exists so a build can be inspected before the fleet is committed to it,
        and a page that offered it anyway would undo that.
        """
        return list(
            await self.session.scalars(
                select(AppVersionModel)
                .where(
                    AppVersionModel.is_current.is_(True),
                    AppVersionModel.published_at.is_not(None),
                )
                .order_by(AppVersionModel.variant, AppVersionModel.version_code.desc())
            )
        )

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


class ReleaseService:
    """The self-hosted update channel (T58, N33, N34).

    The APK is not on Google Play — Play policy prohibits call-recording apps —
    so this table is the distribution record: which build is published, its
    version code, its size, its SHA-256 and when. That record is what makes
    "which build is that phone running" answerable at all.

    **The signing key is the dangerous part.** Android refuses to install a
    differently-signed build as an update; the only way to apply one is to
    uninstall first, which deletes the phone's unsent queue. So the signer is
    read out of the file and compared against the configured fingerprint, and a
    mismatch is a refusal rather than a warning. ``docs/APK-SIGNING.md`` holds
    the fingerprint; until it is filled in, the comparison is skipped and the
    extracted value is recorded so it can be checked by eye.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.store = LocalFsReleaseStore(get_settings().release_storage_path)

    async def list_versions(self) -> tuple[list[AppVersionResponse], int]:
        """Newest build first, both variants. Small table, no pagination."""
        rows = list(
            (
                await self.session.scalars(
                    select(AppVersionModel).order_by(
                        AppVersionModel.version_code.desc(),
                        AppVersionModel.variant,
                    )
                )
            ).all()
        )
        return await self.with_uploader(rows), len(rows)

    async def with_uploader(
        self, rows: list[AppVersionModel]
    ) -> list[AppVersionResponse]:
        """Attach the uploader's name — one query for the whole page, not one
        per row. ``app_versions.created_by`` is a foreign key into ``users``,
        which is what makes reading that table from here allowed (§2)."""
        names = await self._uploader_names([row.created_by for row in rows])
        return [
            AppVersionResponse.model_validate(row).model_copy(
                update={"created_by_name": names.get(row.created_by, "")}
            )
            for row in rows
        ]

    async def _uploader_names(self, ids) -> dict[uuid.UUID, str]:
        wanted = {value for value in ids if value is not None}
        if not wanted:
            return {}
        result = await self.session.execute(
            select(UserModel.id, UserModel.full_name).where(UserModel.id.in_(wanted))
        )
        return {row.id: row.full_name for row in result.all()}

    async def get(self, version_id: uuid.UUID) -> AppVersionModel:
        row = await self.session.get(AppVersionModel, version_id)
        if row is None:
            raise NotFoundError()
        return row

    async def upload(
        self,
        payload: bytes,
        meta: UploadReleaseRequest,
        actor_id: uuid.UUID,
        ip: str | None,
    ) -> tuple[AppVersionModel, ApkInspection]:
        """Store an APK and record it. **Uploaded is not published** (N33).

        Nothing about the file is taken on trust: the SHA-256 and the size are
        computed here rather than accepted, and the signer is read out of the
        signing block. The admin supplies the version code because reading it
        would mean decoding a binary ``AndroidManifest.xml``, and a wrong code
        is caught by the unique constraint and by the phones failing to see an
        update — whereas a wrong *signature* is caught by nothing until fifteen
        people cannot install it.
        """
        inspection = inspect_apk(payload)
        if not inspection.is_apk:
            raise ValidationError(
                ErrorCode.APK_REJECTED, detail={"reason": inspection.reason}
            )

        expected = normalise_fingerprint(get_settings().apk_signing_sha256)
        if not inspection.is_signed:
            raise ValidationError(
                ErrorCode.APK_REJECTED,
                detail={
                    "reason": inspection.reason,
                    "hint": (
                        "a build with no v2/v3 signature will not install on a "
                        "modern Android target"
                    ),
                },
            )
        if expected is not None and inspection.signer_sha256 != expected:
            # Refused, not warned. Installing this over the existing app is
            # impossible; the only route is uninstall-and-reinstall, which
            # destroys every unsent call on the handset.
            raise ValidationError(
                ErrorCode.APK_REJECTED,
                detail={
                    "reason": "signer_mismatch",
                    "expected_sha256": expected,
                    "found_sha256": inspection.signer_sha256,
                },
            )

        clash = await self.session.scalar(
            select(AppVersionModel).where(
                AppVersionModel.variant == meta.variant,
                AppVersionModel.version_code == meta.version_code,
            )
        )
        if clash is not None:
            raise ConflictError(
                ErrorCode.CONFLICT,
                detail={
                    "variant": meta.variant.value,
                    "version_code": meta.version_code,
                    "sha256": clash.apk_sha256,
                },
            )

        key = self.store.key_for(meta.variant.value, meta.version_code)
        stored = self.store.put_bytes(key, payload)
        row = AppVersionModel(
            version=meta.version,
            version_code=meta.version_code,
            variant=meta.variant,
            apk_path=stored.key,
            apk_sha256=stored.sha256,
            size_bytes=stored.bytes,
            min_api_level=meta.min_api_level,
            release_notes_uz=meta.release_notes_uz,
            is_mandatory=meta.is_mandatory,
            created_by=actor_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.APP_VERSION_UPLOADED,
            object_type="app_versions",
            object_id=row.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={
                "variant": meta.variant.value,
                "version_code": meta.version_code,
                "sha256": stored.sha256,
                "signer_sha256": inspection.signer_sha256,
            },
        )
        await self.session.commit()
        log.info(
            "app_version_uploaded",
            version_code=meta.version_code,
            variant=meta.variant.value,
            bytes=stored.bytes,
        )
        return row, inspection

    async def publish(
        self, version_id: uuid.UUID, actor_id: uuid.UUID, ip: str | None
    ) -> AppVersionModel:
        """Make this build the current one for its variant.

        One current build per variant, enforced by a partial unique index, so
        the previous one is stood down in the same transaction. The old build
        is **not** deleted: a phone mid-download still needs those bytes, and
        the distribution record is the point of the table.
        """
        row = await self.get(version_id)
        previous = await self.session.scalar(
            select(AppVersionModel).where(
                AppVersionModel.variant == row.variant,
                AppVersionModel.is_current.is_(True),
                AppVersionModel.id != row.id,
            )
        )
        if previous is not None:
            previous.is_current = False
            await self.session.flush()

        row.is_current = True
        row.published_at = row.published_at or clock.now()
        await self.audit.record(
            action=AuditAction.APP_VERSION_PUBLISHED,
            object_type="app_versions",
            object_id=row.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={
                "variant": row.variant.value,
                "version_code": row.version_code,
                "replaced_version_code": previous.version_code if previous else None,
            },
        )
        await self.session.commit()
        log.info(
            "app_version_published",
            version_code=row.version_code,
            variant=row.variant.value,
        )
        return row

    async def discard(
        self, version_id: uuid.UUID, actor_id: uuid.UUID, ip: str | None
    ) -> None:
        """Remove an **unpublished** build, and only an unpublished one.

        A published build is the distribution record: "which build was current
        in March" has to stay answerable, and a phone may still be downloading
        it. But an upload with a mistyped version code would otherwise occupy
        that code forever — the unique constraint refuses the corrected
        re-upload — so a build that has reached nobody can be taken back.
        """
        row = await self.get(version_id)
        if row.published_at is not None:
            raise ConflictError(
                ErrorCode.CONFLICT,
                detail={
                    "reason": "published",
                    "hint": "publish a newer build instead; the record is kept",
                },
            )
        self.store.delete(row.apk_path)
        await self.audit.record(
            action=AuditAction.APP_VERSION_UPLOADED,
            object_type="app_versions",
            object_id=row.id,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            ip=ip,
            detail={
                "discarded": True,
                "variant": row.variant.value,
                "version_code": row.version_code,
            },
        )
        await self.session.delete(row)
        await self.session.commit()
        log.info("app_version_discarded", version_code=row.version_code)

    async def open_download(self, version_code: int) -> tuple[AppVersionModel, IO[bytes]]:
        """The bytes a phone installs. Published builds only.

        An unpublished row is a 404 and not a 403: this endpoint is public
        (SPEC §4.1 rule 5) and "that build exists but you may not have it" is
        information a stranger has no reason to receive.
        """
        row = await self.session.scalar(
            select(AppVersionModel).where(
                AppVersionModel.version_code == version_code,
                AppVersionModel.published_at.is_not(None),
            )
        )
        if row is None:
            raise NotFoundError()
        return row, self.store.open(row.apk_path)
