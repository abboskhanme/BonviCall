"""Agent administration (T31, SPEC §4.7).

An agent is a person whose calls are attributed; a user is a login. Creating one
here never creates the other, and the panel says so in one Uzbek line.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.permissions import Perm, require_permission
from src.modules.agents.schemas import (
    AgentListResponse,
    AgentResponse,
    CreateAgentRequest,
    ImportAgentsRequest,
    ImportAgentsResponse,
    UpdateAgentRequest,
)
from src.modules.agents.service import AgentService

router = APIRouter(prefix="/agents", tags=["Agents"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get(
    "",
    response_model=AgentListResponse,
    dependencies=[Depends(require_permission(Perm.AGENTS_READ))],
)
async def list_agents(
    session: SessionDep, include_archived: bool = False, q: str | None = None
) -> AgentListResponse:
    items, total = await AgentService(session).list(include_archived, q)
    return AgentListResponse(
        items=[AgentResponse.model_validate(row) for row in items], total=total
    )


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Perm.AGENTS_WRITE))],
)
async def create_agent(
    payload: CreateAgentRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> AgentResponse:
    agent = await AgentService(session).create(payload, principal.id, _client_ip(request))
    return AgentResponse.model_validate(agent)


@router.post(
    "/import",
    response_model=ImportAgentsResponse,
    dependencies=[Depends(require_permission(Perm.AGENTS_WRITE))],
)
async def import_agents(
    payload: ImportAgentsRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> ImportAgentsResponse:
    """A one-off roster import, dry-run by default (T59).

    ~33 people, pasted out of a spreadsheet. The diff is shown before anything
    is written, because a roster import that half-succeeded is harder to
    recover from than one that did not run.
    """
    return await AgentService(session).import_roster(
        payload.csv, payload.dry_run, principal.id, _client_ip(request)
    )


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    dependencies=[Depends(require_permission(Perm.AGENTS_READ))],
)
async def get_agent(agent_id: uuid.UUID, session: SessionDep) -> AgentResponse:
    return AgentResponse.model_validate(await AgentService(session).get(agent_id))


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    dependencies=[Depends(require_permission(Perm.AGENTS_WRITE))],
)
async def update_agent(
    agent_id: uuid.UUID,
    payload: UpdateAgentRequest,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> AgentResponse:
    agent = await AgentService(session).update(
        agent_id, payload, principal.id, _client_ip(request)
    )
    return AgentResponse.model_validate(agent)


@router.post(
    "/{agent_id}/archive",
    response_model=AgentResponse,
    dependencies=[Depends(require_permission(Perm.AGENTS_ARCHIVE))],
)
async def archive_agent(
    agent_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    request: Request,
) -> AgentResponse:
    """409 while the agent still holds an open number assignment."""
    agent = await AgentService(session).archive(agent_id, principal.id, _client_ip(request))
    return AgentResponse.model_validate(agent)
