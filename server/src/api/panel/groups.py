"""Telegram groups for the panel (BonviZvonki ``modules/groups`` router).

═══ ACCESS ═════════════════════════════════════════════════════════════════
``numbers:read`` to look, ``numbers:write`` to change — and the choice needs
stating, because ``core/permissions.py`` is frozen (T18: constants are declared
up front) and there is no ``groups:*`` in it.

A registered number is "a communication channel assigned to an agent, with an
assignment history". A Telegram group is structurally the same object on a
different transport: a chat assigned to an agent, with a binding and a time it
was bound. The role grants land exactly where BonviZvonki puts them — admin and
manager may read, only admin may bind, release or send — so nothing is widened
by reusing them.

**The honest constants would be ``groups:read`` / ``groups:write``**, and
adding them is a one-line change in ``core/permissions.py`` plus the two role
sets. That file is outside this port's remit, so this is the closest existing
fit and the report says so.
═══════════════════════════════════════════════════════════════════════════

⚠️ **Two route orderings are load-bearing** and are commented where they
matter: ``/bulk`` must be declared before ``/{group_id}``, and
``/surveys/broadcast`` before ``/{group_id}/survey``. Starlette matches in
declaration order, so the literal segment would otherwise be parsed as a UUID
and answer 422 — which is how BonviZvonki learned it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from src.core.deps import SessionDep
from src.core.pagination import MAX_LIMIT, Cursor
from src.core.permissions import Perm, require_permission
from src.modules.surveys.groups import GroupRow, GroupService
from src.modules.surveys.schemas import (
    BroadcastRequest,
    BroadcastResponse,
    BroadcastSkip,
    BulkPatchRequest,
    BulkPatchResponse,
    DispatchRequest,
    DispatchResponse,
    GroupPageResponse,
    GroupPatchRequest,
    GroupResponse,
    GroupTreeResponse,
    TreeAgentNode,
    TreeBucket,
)

router = APIRouter(prefix="/groups", tags=["Groups"])

# `groups:*`, declared for this directory on 2026-09-17. It was gated on
# `numbers:*` while the registry was closed to the unit that wrote this module —
# the closest existing meaning, but a Telegram chat is not a registered phone
# line and the matrix should not have to be explained. The role grants are
# unchanged by the swap: admin reads and writes, manager reads.
_read = require_permission(Perm.GROUPS_READ)
_write = require_permission(Perm.GROUPS_WRITE)


def _group(row: GroupRow) -> GroupResponse:
    return GroupResponse(
        id=row.group.id,
        chat_id=row.group.chat_id,
        title=row.group.title,
        agent_id=row.group.agent_id,
        agent_name=row.agent_name,
        agent_color=row.agent_color,
        member_count=row.group.member_count,
        is_active=row.group.is_active,
        bot_status=row.group.bot_status,
        bound_by=row.group.bound_by,
        bound_at=row.group.bound_at,
        last_survey_at=row.group.last_survey_at,
        survey_count=row.survey_count,
        response_count=row.response_count,
    )


@router.get("/tree", response_model=GroupTreeResponse, dependencies=[Depends(_read)])
async def group_tree(session: SessionDep) -> GroupTreeResponse:
    """The page's skeleton: one employee per node, with counts.

    ONE light aggregate. The group rows themselves are pulled only for the node
    somebody opens, 50 at a time — at roughly one group per customer this table
    is a thousand rows, and an endpoint that returned all of them would answer
    no question anybody has and would take a browser with it.
    """
    tree = await GroupService(session).tree()
    return GroupTreeResponse(
        agents=[
            TreeAgentNode(
                agent_id=node.agent_id,
                full_name=node.full_name,
                color=node.color,
                group_count=node.group_count,
                response_count=node.response_count,
            )
            for node in tree.agents
        ],
        unassigned=TreeBucket(
            group_count=tree.unassigned_groups,
            response_count=tree.unassigned_responses,
        ),
    )


@router.get("", response_model=GroupPageResponse, dependencies=[Depends(_read)])
async def list_groups(
    session: SessionDep,
    agent_id: Annotated[uuid.UUID | None, Query()] = None,
    has_agent: Annotated[
        bool | None,
        Query(description="False returns only the groups nobody is bound to."),
    ] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    include_inactive: Annotated[bool, Query()] = False,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> GroupPageResponse:
    """One page of groups, for one opened node.

    ``has_agent=false`` is the query behind the warning bucket at the top of
    the page: those groups will never receive a survey and nothing anywhere
    raises an error about it, so it is the one cut that must be a real
    server-side filter rather than something the panel assembles by walking
    every page.
    """
    page = await GroupService(session).list_groups(
        agent_id=agent_id,
        has_agent=has_agent,
        search=search,
        include_inactive=include_inactive,
        cursor=Cursor.decode(cursor) if cursor else None,
        limit=limit,
    )
    return GroupPageResponse(
        items=[_group(row) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.patch(
    "/bulk", response_model=BulkPatchResponse, dependencies=[Depends(_write)]
)
async def bulk_patch(
    session: SessionDep, body: BulkPatchRequest
) -> BulkPatchResponse:
    """One change applied to up to 200 groups.

    ⚠️ Declared BEFORE ``/{group_id}``: Starlette matches in declaration order,
    and the other way round ``bulk`` is parsed as a UUID and answers 422.

    A larger selection is the panel's problem, and it chunks it — reporting
    each chunk separately, because "400 groups, the first 200 saved and the
    second 200 failed" is something an admin has to be told precisely rather
    than with the single word "error".
    """
    updated = await GroupService(session).bulk_patch(
        body.group_ids,
        agent_id=body.agent_id,
        agent_id_set="agent_id" in body.model_fields_set,
        is_active=body.is_active,
    )
    return BulkPatchResponse(updated=updated)


@router.post(
    "/surveys/broadcast",
    response_model=BroadcastResponse,
    dependencies=[Depends(_write)],
)
async def broadcast(
    session: SessionDep, body: BroadcastRequest | None = None
) -> BroadcastResponse:
    """Queue a survey for every eligible group.

    ⚠️ Declared BEFORE ``/{group_id}/survey``, for the same reason ``/bulk``
    is declared before ``/{group_id}``.

    ⚠️ ``created + reused + len(skipped) == total_groups`` always. A partial
    answer sends an admin to the groups page to count rows and work out what
    happened to the rest.

    ``delivered`` is **0 in this deployment**: the shipped transport posts
    nothing, so the rows sit at ``pending`` and honestly say so.
    """
    outcome = await GroupService(session).broadcast(
        force=body.force if body else True
    )
    return BroadcastResponse(
        created=outcome.created,
        reused=outcome.reused,
        delivered=outcome.delivered,
        total_groups=outcome.total_groups,
        skipped=[
            BroadcastSkip(group_id=item.group_id, title=item.title, reason=item.reason)
            for item in outcome.skipped
        ],
    )


@router.get(
    "/{group_id}", response_model=GroupResponse, dependencies=[Depends(_read)]
)
async def get_group(session: SessionDep, group_id: uuid.UUID) -> GroupResponse:
    return _group(await GroupService(session).get(group_id))


@router.patch(
    "/{group_id}", response_model=GroupResponse, dependencies=[Depends(_write)]
)
async def patch_group(
    session: SessionDep, group_id: uuid.UUID, body: GroupPatchRequest
) -> GroupResponse:
    """Bind, release or park one group.

    Touching the binding by hand marks the row ``manual``, and automatic
    binding then never touches it again. That badge is shown in the list on
    purpose: an admin has to be able to see which rows they are holding.
    """
    row = await GroupService(session).patch(
        group_id,
        agent_id=body.agent_id,
        agent_id_set="agent_id" in body.model_fields_set,
        is_active=body.is_active,
    )
    return _group(row)


@router.delete("/{group_id}", status_code=204, dependencies=[Depends(_write)])
async def delete_group(session: SessionDep, group_id: uuid.UUID) -> Response:
    """Remove a group — refused while the bot is still in the chat (409).

    A chat the bot is sitting in is re-registered on its next message, so the
    delete would look like it worked and then silently undo itself.
    """
    await GroupService(session).delete(group_id)
    return Response(status_code=204)


@router.post(
    "/{group_id}/survey",
    response_model=DispatchResponse,
    status_code=201,
    dependencies=[Depends(_write)],
)
async def send_survey(
    session: SessionDep, group_id: uuid.UUID, body: DispatchRequest | None = None
) -> DispatchResponse:
    """Queue a survey for one group.

    Two of the 409s are ordinary states rather than faults, and the panel shows
    the reason instead of a red error: ``group_not_bound`` (nobody to
    attribute the rating to) and ``survey_suppressed`` (asked too recently).
    The second is cleared by ``force``; the first never is.
    """
    outcome = await GroupService(session).create_survey(
        group_id, force=body.force if body else False
    )
    return DispatchResponse(
        survey_id=outcome.survey_id,
        status=outcome.status,
        reused=outcome.reused,
        delivered=outcome.delivered,
    )
