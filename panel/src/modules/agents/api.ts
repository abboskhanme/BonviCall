/**
 * Agents — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * An agent is a salesperson, **not** a login: `POST /agents` never creates a
 * user and `POST /users` never creates an agent (SPEC §4.7). The one link is
 * `UserResponse.agent_id`, and `/users` is a different page.
 *
 * `useAgentDirectory` lives here rather than in `modules/calls/api.ts`, where
 * PN-CALLS had to park it: every rollout page needs to turn an `agent_id` into
 * a name, and four copies of that lookup is four things to fix when the roster
 * endpoint grows a cursor.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type Agent = components['schemas']['AgentResponse']
export type AgentList = components['schemas']['AgentListResponse']
export type CreateAgentRequest = components['schemas']['CreateAgentRequest']
export type UpdateAgentRequest = components['schemas']['UpdateAgentRequest']

/** The roster. Unpaginated by contract — a few hundred rows at most. */
export function useAgents(params: {
  q?: string | undefined
  includeArchived?: boolean
}): UseQueryResult<AgentList> {
  const query = {
    ...(params.q ? { q: params.q } : {}),
    include_archived: params.includeArchived ?? false,
  }
  return useQuery({
    queryKey: queryKey('agents', 'list', query),
    queryFn: () => api.get<AgentList>('/agents', query),
  })
}

/**
 * Agent id → name, for every page that receives an id and must show a person.
 *
 * `enabled` is the caller's decision and must be `can('agents:read')`: a
 * `sales` user does not hold it and would get a 403 that means nothing to
 * them. Archived agents are included on purpose — a call, an assignment or an
 * installation from six months ago still belongs to somebody who has left, and
 * an empty cell there reads as data loss.
 */
export function useAgentDirectory(enabled: boolean): UseQueryResult<AgentList> {
  return useQuery({
    queryKey: queryKey('agents', 'directory'),
    queryFn: () => api.get<AgentList>('/agents', { include_archived: true }),
    enabled,
    // The roster changes a few times a month; polling it behind every list is
    // noise on a page that already refetches its own data every 15 seconds.
    refetchInterval: false,
    staleTime: 5 * 60_000,
  })
}

/** A lookup the pages can call without caring whether the directory loaded. */
export function agentNameLookup(agents: Agent[] | undefined): (id: string) => string | null {
  const byId = new Map((agents ?? []).map((agent) => [agent.id, agent.full_name]))
  return (id: string) => byId.get(id) ?? null
}

export function useAgent(agentId: string | undefined): UseQueryResult<Agent> {
  return useQuery({
    queryKey: queryKey('agents', 'detail', { agentId }),
    queryFn: () => api.get<Agent>(`/agents/${agentId}`),
    enabled: Boolean(agentId),
  })
}

export function useCreateAgent(): UseMutationResult<Agent, unknown, CreateAgentRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateAgentRequest) => api.post<Agent>('/agents', body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('agents') })
    },
  })
}

export function useUpdateAgent(
  agentId: string,
): UseMutationResult<Agent, unknown, UpdateAgentRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateAgentRequest) => api.patch<Agent>(`/agents/${agentId}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('agents') })
    },
  })
}

/**
 * Archive, not delete.
 *
 * 409 `agent_has_open_assignment` when the agent still holds a line: closing
 * the assignment is a decision about who owns the calls from now on, and the
 * server refuses to make it silently. The modal surfaces that code as its
 * Uzbek sentence rather than a generic failure.
 */
export function useArchiveAgent(agentId: string): UseMutationResult<Agent, unknown, void> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<Agent>(`/agents/${agentId}/archive`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('agents') })
      // An archived agent changes what the numbers page shows as the holder.
      void client.invalidateQueries({ queryKey: moduleKey('numbers') })
    },
  })
}

/** One agent's current line, as the roster shows it. */
export interface AgentLine {
  e164: string
  /** When this agent was given the number — the assignment's `valid_from`,
   *  which is NOT the same fact as `hired_at`. */
  since: string
}

/**
 * Which work number each agent holds right now, and since when.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ **This fans out: one request per agent.**
 *
 * `AgentResponse` carries neither the number nor the assignment date, so the
 * only way to put them on the roster is to read every agent's assignments and
 * join them against `/numbers`. At fifteen agents that is fifteen small cached
 * requests and it works; at three hundred it does not.
 *
 * The fix is the denormalisation `CallResponse` already has — `agent_name`
 * arrives with the row rather than being looked up per row — and the same
 * shape here would be `current_number_e164` and `number_since` on
 * `AgentResponse`. **TODO(server): add them and delete this hook.**
 *
 * `since` comes from the assignment and never from `hired_at`. They are
 * different facts: one is when this person was given this line, the other is
 * when they were employed, and labelling the second as the first would put a
 * false caption on real data.
 * ═══════════════════════════════════════════════════════════════════════════
 */
export function useAgentLines(
  agents: Agent[] | undefined,
  numbers: { id: string; e164: string }[] | undefined,
): { lines: Map<string, AgentLine>; isError: boolean } {
  const results = useQueries({
    queries: (agents ?? []).map((agent) => ({
      queryKey: queryKey('numbers', 'agentAssignments', { agentId: agent.id }),
      queryFn: () =>
        api.get<{ items: AssignmentRow[] }>('/assignments', { agent_id: agent.id }),
      staleTime: 60_000,
    })),
  })

  const e164ById = new Map((numbers ?? []).map((number) => [number.id, number.e164]))
  const lines = new Map<string, AgentLine>()
  ;(agents ?? []).forEach((agent, index) => {
    // The OPEN assignment only: a closed one is history, and the roster is
    // asking what they hold today. The card shows the full timeline.
    const open = results[index]?.data?.items.find((row) => row.valid_to === null)
    const e164 = open ? e164ById.get(open.number_id) : undefined
    if (open && e164) lines.set(agent.id, { e164, since: open.valid_from })
  })

  return { lines, isError: results.some((result) => result.status === 'error') }
}

interface AssignmentRow {
  number_id: string
  valid_from: string
  valid_to: string | null
}
