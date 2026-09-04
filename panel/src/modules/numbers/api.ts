/**
 * Work numbers, their time-boxed assignments, and enrolment codes.
 *
 * **Module mapping (CONVENTIONS-CLIENT.md §1 asks for this note).** This panel
 * module has no page of its own: `/numbers` and `/enrolment` were removed on
 * 2026-09-05 at the client's request, because for a fifteen-person team
 * registering a line and issuing a code are things you do *to an agent*. The
 * UI lives on `/agents/:id`; the hooks live here because they read the
 * server's `numbers` and `enrolment` modules, and folding them into
 * `modules/agents/api.ts` would hide which service actually answers.
 *
 * The assignment is **time-boxed**, and that is the whole point of the model:
 * `[valid_from, valid_to)`. A number that moved from one agent to another has
 * history, and calls made before the handover still belong to the previous
 * holder (SPEC §3.3, D-08). Nothing here may present "the current holder" as
 * if it were the only truth.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components } from '@/shared/api/types.gen'

export type RegisteredNumber = components['schemas']['NumberResponse']
export type NumberList = components['schemas']['NumberListResponse']
export type Assignment = components['schemas']['AssignmentResponse']
export type AssignmentList = components['schemas']['AssignmentListResponse']
export type CreateNumberRequest = components['schemas']['CreateNumberRequest']
export type CreateAssignmentRequest = components['schemas']['CreateAssignmentRequest']
export type CloseAssignmentRequest = components['schemas']['CloseAssignmentRequest']
export type EnrolmentCode = components['schemas']['EnrolmentCodeResponse']
export type EnrolmentCodeList = components['schemas']['EnrolmentCodeListResponse']
export type EnrolmentAttempt = components['schemas']['EnrolmentAttemptResponse']
export type EnrolmentAttemptList = components['schemas']['EnrolmentAttemptListResponse']

/** Every registered line. Unpaginated by contract, and small by nature. */
export function useNumbers(isActive?: boolean): UseQueryResult<NumberList> {
  const query = isActive === undefined ? {} : { is_active: isActive }
  return useQuery({
    queryKey: queryKey('numbers', 'list', query),
    queryFn: () => api.get<NumberList>('/numbers', query),
  })
}

/** The full holding history of one line — this is the timeline. */
export function useAssignments(numberId: string | undefined): UseQueryResult<AssignmentList> {
  return useQuery({
    queryKey: queryKey('numbers', 'assignments', { numberId }),
    queryFn: () => api.get<AssignmentList>(`/numbers/${numberId}/assignments`),
    enabled: Boolean(numberId),
  })
}

export interface AgentAssignment {
  assignment: Assignment
  number: RegisteredNumber
}

/**
 * Which lines this agent holds, or has ever held.
 *
 * One request. This used to fan out across every registered number, because
 * there was no way to ask the question directly; `GET /assignments?agent_id=`
 * now exists and the fan-out is gone.
 *
 * **Closed assignments are kept deliberately.** An agent who handed their line
 * over last month still owns the calls from before the handover — attribution
 * uses `started_at`, so a call does not follow the number (SPEC §3.3, D-08) —
 * and a page showing only the open assignment would make those calls look
 * unattributed on exactly the day somebody asks about them.
 */
export function useAgentAssignments(agentId: string | undefined): UseQueryResult<AssignmentList> {
  return useQuery({
    queryKey: queryKey('numbers', 'agentAssignments', { agentId }),
    queryFn: () => api.get<AssignmentList>('/assignments', { agent_id: agentId }),
    enabled: Boolean(agentId),
  })
}

/** Join the assignments to the lines they are about, newest holding first. */
export function agentAssignmentRows(
  assignments: Assignment[] | undefined,
  numbers: RegisteredNumber[] | undefined,
): AgentAssignment[] {
  const byId = new Map((numbers ?? []).map((number) => [number.id, number]))
  const rows: AgentAssignment[] = []
  for (const assignment of assignments ?? []) {
    const number = byId.get(assignment.number_id)
    if (number) rows.push({ assignment, number })
  }
  // An open period (valid_to === null) is the newest by definition.
  rows.sort((a, b) => b.assignment.valid_from.localeCompare(a.assignment.valid_from))
  return rows
}

/**
 * A code is usable only while it is none of spent, revoked or expired.
 *
 * All three are separate columns rather than one status, because they are
 * three different conversations with the agent: "you already used it",
 * "an admin cancelled it" and "it ran out" each have a different next step.
 */
export function isCodeLive(code: EnrolmentCode, now: number = Date.now()): boolean {
  if (code.redeemed_at !== null || code.revoked_at !== null) return false
  return new Date(code.expires_at).getTime() > now
}

/** `valid_to === null` means they hold it now — the period is half-open. */
export function isOpen(assignment: Assignment): boolean {
  return assignment.valid_to === null
}

export function useCreateNumber(): UseMutationResult<
  RegisteredNumber,
  unknown,
  CreateNumberRequest
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateNumberRequest) => api.post<RegisteredNumber>('/numbers', body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('numbers') })
    },
  })
}

/**
 * Hand a line to an agent.
 *
 * 409 `number_already_assigned` names the current holder in `detail` (UC-01's
 * acceptance criterion), so the modal shows who has it rather than "conflict".
 */
export interface AssignVariables {
  numberId: string
  body: CreateAssignmentRequest
}

export function useAssignNumber(): UseMutationResult<Assignment, unknown, AssignVariables> {
  const client = useQueryClient()
  return useMutation({
    // The number id is a mutation VARIABLE, not a hook argument, so that
    // "register a new line and hand it over" can assign to an id that did not
    // exist when this hook was created. Binding it at hook level would make
    // the follow-up call fire against a stale id.
    mutationFn: ({ numberId, body }: AssignVariables) =>
      api.post<Assignment>(`/numbers/${numberId}/assignments`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('numbers') })
      // Re-attribution runs server-side, so previously listed calls may now
      // belong to somebody else.
      void client.invalidateQueries({ queryKey: moduleKey('calls') })
    },
  })
}

/** Close a holding period. Triggers `reattribute_calls` server-side. */
export function useCloseAssignment(
  assignmentId: string,
): UseMutationResult<Assignment, unknown, CloseAssignmentRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CloseAssignmentRequest) =>
      api.patch<Assignment>(`/assignments/${assignmentId}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('numbers') })
      void client.invalidateQueries({ queryKey: moduleKey('calls') })
    },
  })
}

/** Codes issued for one line, newest first. */
export function useEnrolmentCodes(numberId: string | undefined): UseQueryResult<EnrolmentCodeList> {
  return useQuery({
    queryKey: queryKey('enrolment', 'codes', { numberId }),
    queryFn: () => api.get<EnrolmentCodeList>('/enrolment-codes', { number_id: numberId }),
    enabled: Boolean(numberId),
  })
}

/**
 * Issue a code. **This is the action that starts everything** — until it
 * happens the agent has nothing to install and no way to enrol.
 */
export function useIssueEnrolmentCode(
  numberId: string,
): UseMutationResult<EnrolmentCode, unknown, void> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<EnrolmentCode>(`/numbers/${numberId}/enrolment-code`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('enrolment') })
    },
  })
}

export function useRevokeEnrolmentCode(): UseMutationResult<EnrolmentCode, unknown, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (codeId: string) => api.post<EnrolmentCode>(`/enrolment-codes/${codeId}/revoke`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('enrolment') })
    },
  })
}

/**
 * Enrolment attempts for one line — where UC-01's failures appear, with
 * timestamps. This is what answers "they say it will not work; at which step?"
 */
export function useEnrolmentAttempts(
  numberId: string | undefined,
): UseQueryResult<EnrolmentAttemptList> {
  return useQuery({
    queryKey: queryKey('enrolment', 'attempts', { numberId }),
    queryFn: () => api.get<EnrolmentAttemptList>('/enrolment/attempts', { number_id: numberId }),
    enabled: Boolean(numberId),
  })
}

/**
 * The callback receiver's health.
 *
 * Generated now: the route used to be declared `-> dict[str, str | bool]` and
 * reached the contract as `additionalProperties`, so the panel had to parse it
 * defensively. It has a real `ReceiverStatusResponse` model, so the hand-rolled
 * guard is gone and a field rename is a compile error again.
 */
export type ReceiverStatus = components['schemas']['ReceiverStatusResponse']

export function useReceiverStatus(enabled: boolean): UseQueryResult<ReceiverStatus> {
  return useQuery({
    queryKey: queryKey('enrolment', 'receiver'),
    queryFn: () => api.get<ReceiverStatus>('/enrolment/receiver-status'),
    enabled,
  })
}
