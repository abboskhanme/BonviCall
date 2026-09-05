/**
 * The dialog that ends on the enrolment code.
 *
 * The client could not find where the code came from, so the dialog must not
 * close and leave them hunting: it becomes the receipt. And because the
 * employee code (`BV-001`) was typed into the app when it asked for the
 * enrolment code (`W4WH6KRA`), the code is labelled by what it does and shown
 * with its shape — those two are pinned here so a later tidy-up cannot quietly
 * make them the same word again.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CreateAgentModal } from '@/modules/agents/CreateAgentModal'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

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

function server(overrides: { assign?: () => Response } = {}) {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/api/v1/agents')) return Promise.resolve(json(200, AGENT))
    if (url.includes('/enrolment-code')) return Promise.resolve(json(201, CODE))
    if (url.includes('/assignments')) {
      return Promise.resolve((overrides.assign ?? (() => json(201, {})))())
    }
    if (url.includes('/api/v1/numbers')) return Promise.resolve(json(201, NUMBER))
    return Promise.resolve(json(200, {}))
  })
}

function renderModal(onOpenChange = () => {}) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <CreateAgentModal open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
}

async function fillAndSubmit(number = '+998901112233') {
  await userEvent.type(screen.getByLabelText(t('agents.fieldName')), 'Aziz Karimov')
  if (number) await userEvent.type(screen.getByLabelText(t('agents.fieldNumber')), number)
  await userEvent.click(screen.getByRole('button', { name: t('agents.createAction') }))
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  Object.assign(navigator, { clipboard: { writeText: vi.fn(async () => {}) } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('one dialog, one outcome', () => {
  it('ends on the code rather than closing', async () => {
    const onOpenChange = vi.fn()
    server()
    renderModal(onOpenChange)
    await fillAndSubmit()

    // The whole point: the admin sees what they just created.
    expect(await screen.findByText('W4WH6KRA')).toBeInTheDocument()
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })

  it('says what the code is FOR, and what shape it is', async () => {
    server()
    renderModal()
    await fillAndSubmit()

    await screen.findByText('W4WH6KRA')
    // `BV-001` was typed into the app when it asked for this. Naming it by
    // what it does, and stating its shape, is what makes that visible.
    expect(screen.getByText(t('enrol.codeCardTitle'))).toBeInTheDocument()
    expect(screen.getByText(t('enrol.codeShape'))).toBeInTheDocument()
  })

  it('warns on the employee-code field that it is not the app code', async () => {
    server()
    renderModal()
    expect(screen.getByText(t('agents.fieldCodeNotEnrolment'))).toBeInTheDocument()
  })

  it('offers the copy-link action beside the code', async () => {
    server()
    renderModal()
    await fillAndSubmit()

    await screen.findByText('W4WH6KRA')
    await userEvent.click(screen.getByRole('button', { name: t('enrol.copyLink') }))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled())
    const sent = vi.mocked(navigator.clipboard.writeText).mock.calls[0]?.[0] ?? ''
    expect(sent).toContain('/i/W4WH6KRA')
  })

  it('does not require a number', async () => {
    server()
    renderModal()
    await userEvent.type(screen.getByLabelText(t('agents.fieldName')), 'Aziz Karimov')
    // The roster is also used for people who have not been issued a line yet.
    expect(screen.getByRole('button', { name: t('agents.createAction') })).toBeEnabled()
  })
})

describe('a partial failure says exactly what happened', () => {
  it('reports the agent as created when the assignment conflicts', async () => {
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
    renderModal()
    await fillAndSubmit()

    // An agent the admin believes failed, but which exists, is how a roster
    // grows a second Aziz Karimov.
    expect(
      await screen.findByText(t('agents.stepAgent', { name: 'Aziz Karimov' })),
    ).toBeInTheDocument()
    expect(screen.getByText(t('agents.stepAssignFailed'))).toBeInTheDocument()
    // And it names who actually holds the line (UC-01).
    expect(
      screen.getByText(t('numbers.alreadyHeldBy', { name: 'Sanjar Toshev' })),
    ).toBeInTheDocument()
    expect(screen.getByText(t('agents.partialHint'))).toBeInTheDocument()
    // No code was issued, so none is shown.
    expect(screen.queryByText(t('enrol.codeCardTitle'))).toBeNull()
  })

  it('says a number was reused rather than created', async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/v1/agents')) return Promise.resolve(json(200, AGENT))
      if (url.includes('/enrolment-code')) return Promise.resolve(json(201, CODE))
      if (url.includes('/assignments')) return Promise.resolve(json(201, {}))
      if (url.match(/\/api\/v1\/numbers\/[^/]+$/)) return Promise.resolve(json(200, NUMBER))
      return Promise.resolve(
        json(409, {
          error: { code: 'conflict', message: '', detail: { field: 'e164', existing_id: 'number-1' } },
        }),
      )
    })
    renderModal()
    await fillAndSubmit()

    await screen.findByText('W4WH6KRA')
    // Normal, not a failure — but worth saying, so the admin is not surprised
    // to find the line already has history.
    expect(
      screen.getByText(t('agents.stepNumberReused', { number: '+998 90 111 22 33' })),
    ).toBeInTheDocument()
  })
})
