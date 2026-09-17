"""The scoring rubric, viewable and editable in the panel (SPEC-ANALYTICS §2.5).

WHERE THIS IS MOUNTED, AND WHY. ``api/panel/analysis.py`` includes this router,
so the paths are ``/api/v1/analysis/rubric...``. The rubric is not a section of
its own — it is the criteria the TAHLIL section scores against, and a reader who
finds a score wrong goes from that score to these criteria. Mounting it under
``/analysis`` puts the URL where the menu already is, and keeps
``api/panel/__init__.py`` untouched while two other units are editing it.

PERMISSIONS. Reading is ``analysis:read``, so whoever may read a score may read
the criteria it was produced against — a score whose rubric is invisible is a
number nobody can argue with. Publishing is ``settings:write``, which is
**admin only**: the registry draws its admin-only line there for exactly this
kind of change, one that alters how the system behaves for everybody afterwards
and costs money on every call (``extra_rules`` is sent with each one). A manager
holds ``settings:read`` and ``analysis:read`` and therefore reads the rubric and
cannot change it — the same line as ``settings:write`` and
``installations:revoke``.

*If a dedicated ``rubric:write`` is later added to the registry, it replaces the
dependency on these two write routes and nothing else moves; the role matrix
would be identical, because ``settings:write`` is admin-only today.*

EDITING PUBLISHES. There is no PATCH and no rubric id in any request body. The
version that produced yesterday's scores is never modified, because
``call_scores.rubric_version`` names it and that string has to keep meaning what
it says.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_permission
from src.modules.analysis.rubric_service import (
    RubricService,
    prompt_preview,
    rubric_response,
    version_summary,
)
from src.modules.analysis.schemas import (
    PublishRubricRequest,
    RubricPromptResponse,
    RubricResponse,
    RubricVersionListResponse,
)

router = APIRouter(prefix="/rubric", tags=["Rubric"])

_read = require_permission(Perm.ANALYSIS_READ)
_write = require_permission(Perm.SETTINGS_WRITE)


@router.get("", response_model=RubricResponse, dependencies=[Depends(_read)])
async def get_active_rubric(session: SessionDep) -> RubricResponse:
    """The rubric new scores are produced against.

    Answers 200 even when nothing has been published: the response is then the
    rubric pinned in ``rubric_default.py`` with ``stored: false``, which is
    exactly what such a database scores with. Reading does **not** create the
    row — BonviZvonki's version did, which made this GET a write.
    """
    return rubric_response(await RubricService(session).active())


@router.get(
    "/versions", response_model=RubricVersionListResponse, dependencies=[Depends(_read)]
)
async def list_rubric_versions(session: SessionDep) -> RubricVersionListResponse:
    """Every published version, newest first.

    Not paged: a rubric is published a handful of times a year, and the history
    is the audit trail of "who changed how people are scored, and when" — which
    is worth reading whole.
    """
    rows = await RubricService(session).versions()
    return RubricVersionListResponse(
        items=[version_summary(row) for row in rows], total=len(rows)
    )


@router.get("/prompt", response_model=RubricPromptResponse, dependencies=[Depends(_read)])
async def get_rubric_prompt(session: SessionDep) -> RubricPromptResponse:
    """What is actually sent to the model, assembled from the active rubric.

    Read-only, and the sections say which single one is editable. An admin who
    cannot see this text edits blind; an admin who could edit all of it could
    break the response format and stop every score from validating.
    """
    return prompt_preview(await RubricService(session).active())


@router.put("", response_model=RubricResponse, dependencies=[Depends(_write)])
async def publish_rubric(
    payload: PublishRubricRequest, principal: PrincipalDep, session: SessionDep
) -> RubricResponse:
    """Publish the next version and make it active.

    422 ``validation_error`` with a ``reason`` in the detail when the rubric
    cannot produce a comparable score — the blocks not totalling 100 is the
    first of those reasons, and the rubric is **not saved**.
    """
    row = await RubricService(session).publish(
        name=payload.name,
        description=payload.description,
        blocks=[block.model_dump() for block in payload.blocks],
        red_flags=[flag.model_dump() for flag in payload.red_flags],
        extra_rules=payload.extra_rules,
        user_id=principal.id,
    )
    return rubric_response(row)


@router.post(
    "/versions/{version}/activate",
    response_model=RubricResponse,
    dependencies=[Depends(_write)],
)
async def activate_rubric_version(version: int, session: SessionDep) -> RubricResponse:
    """Go back to an earlier version — the undo for a bad edit.

    The version keeps its own number rather than being re-published under a new
    one, so scores written before and after the round trip carry the same label
    and really were produced by the same criteria.
    """
    return rubric_response(await RubricService(session).activate(version))
