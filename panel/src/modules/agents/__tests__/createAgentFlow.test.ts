/**
 * Getting one salesperson onto the system, in one flow.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Four server calls behind one button, and the thing that matters is what
 * happens when the third one fails.
 *
 * **A partial failure must not strand anybody.** An agent with no number is
 * recoverable in thirty seconds. An agent the admin believes failed — but
 * which actually exists — is how a roster of fifteen people grows a second
 * Aziz Karimov, and nobody notices until two months of calls have been filed
 * under the wrong one. So every step records what it did, and the record
 * survives the failure of a later step.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { conflictingHolder, createAgentWithNumber } from '@/modules/agents/createAgentFlow'
import { tokenStore } from '@/shared/api/client'

const fetchMock = vi.fn<typeof fetch>()

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const AGENT = { id: 'agent-1', full_name: 'Aziz Karimov' }
const NUMBER = { id: 'number-1', e164: '+998901112233' }
const CODE = { id: 'code-1', code: 'W4WH6KRA', expires_at: '2026-09-06T12:00:00+05:00' }

/** Route by URL and method, so the order of calls is not baked into the test. */
function server(handlers: {
  agent?: () => Response
  createNumber?: () => Response
  getNumber?: () => Response
  assign?: () => Response
  code?: () => Response
}) {
  fetchMock.mockImplementation((input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/api/v1/agents')) return Promise.resolve((handlers.agent ?? (() => json(200, AGENT)))())
    if (url.includes('/enrolment-code')) return Promise.resolve((handlers.code ?? (() => json(201, CODE)))())
    if (url.includes('/assignments')) return Promise.resolve((handlers.assign ?? (() => json(201, {})))())
    if (url.includes('/api/v1/numbers/') && method === 'GET') {
      return Promise.resolve((handlers.getNumber ?? (() => json(200, NUMBER)))())
    }
    if (url.includes('/api/v1/numbers')) {
      return Promise.resolve((handlers.createNumber ?? (() => json(201, NUMBER)))())
    }
    return Promise.resolve(json(200, {}))
  })
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

const INPUT = { agent: { full_name: 'Aziz Karimov' }, e164: '+998901112233' }

describe('the whole way through', () => {
  it('creates the agent, the number, the assignment and the code', async () => {
    server({})
    const result = await createAgentWithNumber(INPUT)

    expect(result.failedAt).toBeNull()
    expect(result.agent?.id).toBe('agent-1')
    expect(result.number?.id).toBe('number-1')
    expect(result.assigned).toBe(true)
    expect(result.code?.code).toBe('W4WH6KRA')
    expect(result.reusedNumber).toBe(false)
  })

  it('stops after the agent when no number was asked for', async () => {
    server({})
    // An agent may exist with no line — the roster is also used for people who
    // have not been issued one, and forcing a number would refuse that.
    const result = await createAgentWithNumber({ agent: { full_name: 'Aziz Karimov' } })

    expect(result.failedAt).toBeNull()
    expect(result.agent).not.toBeNull()
    expect(result.number).toBeNull()
    expect(result.code).toBeNull()
    // Nothing was attempted beyond the agent.
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/numbers'))).toHaveLength(0)
  })
})

describe('a number that is already registered', () => {
  it('reuses it instead of failing', async () => {
    // Ordinary: a line handed from one salesperson to the next. The server
    // answers 409 with `detail.existing_id`, and reading it out of the error
    // is what turns this back into the happy path.
    server({
      createNumber: () =>
        json(409, {
          error: {
            code: 'conflict',
            message: 'exists',
            detail: { field: 'e164', existing_id: 'number-1' },
          },
        }),
    })

    const result = await createAgentWithNumber(INPUT)

    expect(result.failedAt).toBeNull()
    expect(result.number?.id).toBe('number-1')
    expect(result.reusedNumber).toBe(true)
    expect(result.code?.code).toBe('W4WH6KRA')
  })

  it('does not mistake an unrelated 409 for a reusable number', async () => {
    server({
      createNumber: () =>
        json(409, { error: { code: 'conflict', message: 'something else', detail: {} } }),
    })

    const result = await createAgentWithNumber(INPUT)

    // No `existing_id` means there is nothing to reuse, and pretending
    // otherwise would assign a number that was never resolved.
    expect(result.failedAt).toBe('number')
    expect(result.number).toBeNull()
  })
})

describe('partial failure keeps the record', () => {
  it('remembers the agent when the number fails', async () => {
    server({ createNumber: () => json(500, { error: { code: 'internal_error', message: '' } }) })

    const result = await createAgentWithNumber(INPUT)

    expect(result.failedAt).toBe('number')
    // THE point: the agent exists and the dialog must say so, or the admin
    // creates them again.
    expect(result.agent?.full_name).toBe('Aziz Karimov')
    expect(result.number).toBeNull()
  })

  it('remembers the agent and the number when the assignment conflicts', async () => {
    server({
      assign: () =>
        json(409, {
          error: {
            code: 'number_already_assigned',
            message: 'taken',
            detail: { agent_name: 'Sanjar Toshev' },
          },
        }),
    })

    const result = await createAgentWithNumber(INPUT)

    expect(result.failedAt).toBe('assignment')
    expect(result.agent).not.toBeNull()
    expect(result.number).not.toBeNull()
    expect(result.assigned).toBe(false)
    // UC-01: the conflict names the current holder, which is the only thing
    // the admin can act on.
    expect(conflictingHolder(result.error)).toBe('Sanjar Toshev')
  })

  it('remembers everything when only the code fails', async () => {
    server({ code: () => json(500, { error: { code: 'internal_error', message: '' } }) })

    const result = await createAgentWithNumber(INPUT)

    expect(result.failedAt).toBe('code')
    expect(result.agent).not.toBeNull()
    expect(result.number).not.toBeNull()
    // The assignment stands: only the last step is missing, and it can be
    // reissued from the agent's card.
    expect(result.assigned).toBe(true)
    expect(result.code).toBeNull()
  })

  it('attempts nothing after the agent itself fails', async () => {
    server({ agent: () => json(409, { error: { code: 'conflict', message: '' } }) })

    const result = await createAgentWithNumber(INPUT)

    expect(result.failedAt).toBe('agent')
    expect(result.agent).toBeNull()
    // No orphan number, no orphan code.
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/numbers'))).toHaveLength(0)
  })
})

describe('conflictingHolder', () => {
  it('reads the name only from the assignment conflict', async () => {
    server({
      assign: () =>
        json(409, {
          error: { code: 'number_already_assigned', message: '', detail: { agent_name: 'Malika' } },
        }),
    })
    const result = await createAgentWithNumber(INPUT)
    expect(conflictingHolder(result.error)).toBe('Malika')
  })

  it('returns null for anything else', () => {
    expect(conflictingHolder(null)).toBeNull()
    expect(conflictingHolder(new Error('x'))).toBeNull()
  })
})
