/**
 * Getting one salesperson onto the system, in one call from the UI's side.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Enrolling somebody used to take three places: create the agent here, find
 * their card to assign a number, then find the enrolment section to issue a
 * code. The third step was invisible — the person who commissioned this system
 * could not find where the code came from.
 *
 * So it is four server calls behind one button:
 *
 *   1. POST /agents                           the person
 *   2. POST /numbers                          the line, unless it exists
 *   3. POST /numbers/{id}/assignments         the line is theirs, from now
 *   4. POST /numbers/{id}/enrolment-code      the code they type into the app
 *
 * **Every step records what it did, and the flow never throws away that
 * record.** A partial failure has to be reportable: an agent who exists but
 * has no number is recoverable in thirty seconds, whereas an agent the admin
 * believes failed — and who actually exists — is how a roster ends up with two
 * Aziz Karimovs. So the result is a `FlowResult` describing exactly how far it
 * got, and the caller renders that rather than a success/failure boolean.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { api } from '@/shared/api/client'
import { isApiError } from '@/shared/api/errors'
import type { Agent, CreateAgentRequest } from './api'
import type { EnrolmentCode, RegisteredNumber } from '@/modules/numbers/api'

/** How far the flow got. Each step is only attempted if the previous one
 *  produced what it needs. */
export type FlowStep = 'agent' | 'number' | 'assignment' | 'code'

export interface FlowResult {
  agent: Agent | null
  number: RegisteredNumber | null
  assigned: boolean
  code: EnrolmentCode | null
  /** The step that failed, or null when everything asked for was done. */
  failedAt: FlowStep | null
  error: unknown
  /** Set when the line was already registered and was reused rather than
   *  created — normal, and worth telling the admin so they are not surprised
   *  to find it already had history. */
  reusedNumber: boolean
}

export interface CreateAgentInput {
  agent: CreateAgentRequest
  /** Optional: an agent may exist with no line yet, and forcing one would
   *  make the form refuse a legitimate case. */
  e164?: string
  simOwner?: string
}

/**
 * Reuse a line that is already registered.
 *
 * `POST /numbers` answers 409 with `detail.existing_id` when the number is
 * already in the system, which is an ordinary situation — a line handed from
 * one salesperson to the next — and not a failure. Reading the id out of the
 * error is what turns it back into the happy path; the genuine conflict is the
 * ASSIGNMENT, which is a different call and a different code.
 */
function existingNumberId(error: unknown): string | null {
  if (!isApiError(error) || error.status !== 409) return null
  const detail = error.detail
  const id = detail?.existing_id
  return typeof id === 'string' && id.length > 0 ? id : null
}

export async function createAgentWithNumber(input: CreateAgentInput): Promise<FlowResult> {
  const result: FlowResult = {
    agent: null,
    number: null,
    assigned: false,
    code: null,
    failedAt: null,
    error: null,
    reusedNumber: false,
  }

  // ── 1. the person ──────────────────────────────────────────────────────
  try {
    result.agent = await api.post<Agent>('/agents', input.agent)
  } catch (error) {
    result.failedAt = 'agent'
    result.error = error
    return result
  }

  const e164 = input.e164?.trim()
  if (!e164) return result

  // ── 2. the line, unless it is already registered ───────────────────────
  try {
    result.number = await api.post<RegisteredNumber>('/numbers', {
      e164,
      sim_owner: input.simOwner ?? 'company',
    })
  } catch (error) {
    const id = existingNumberId(error)
    if (id === null) {
      result.failedAt = 'number'
      result.error = error
      return result
    }
    try {
      result.number = await api.get<RegisteredNumber>(`/numbers/${id}`)
      result.reusedNumber = true
    } catch (lookupError) {
      result.failedAt = 'number'
      result.error = lookupError
      return result
    }
  }

  // ── 3. the line is theirs, from now ────────────────────────────────────
  try {
    await api.post(`/numbers/${result.number.id}/assignments`, { agent_id: result.agent.id })
    result.assigned = true
  } catch (error) {
    // 409 `number_already_assigned` names the current holder in `detail`, and
    // that name is the only thing the admin can act on.
    result.failedAt = 'assignment'
    result.error = error
    return result
  }

  // ── 4. the code they type into the app ─────────────────────────────────
  try {
    result.code = await api.post<EnrolmentCode>(`/numbers/${result.number.id}/enrolment-code`)
  } catch (error) {
    result.failedAt = 'code'
    result.error = error
  }

  return result
}

/** The holder named by a 409 on the assignment step (UC-01's criterion). */
export function conflictingHolder(error: unknown): string | null {
  if (!isApiError(error) || error.code !== 'number_already_assigned') return null
  const name = error.detail?.agent_name
  return typeof name === 'string' && name.length > 0 ? name : null
}
