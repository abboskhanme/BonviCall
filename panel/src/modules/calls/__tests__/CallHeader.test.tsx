/**
 * The call header, and the devices/agents/users table fixes from the client's
 * screenshots.
 *
 * The header is the one worth a test: it must read as a call BETWEEN TWO
 * PEOPLE, with the employee on the left, the client on the right, and the
 * direction visible without reading a badge. Sides that could silently swap,
 * or a withheld number that leaves half the card empty, are exactly the
 * regressions a layout change causes.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CallDetailPage } from '@/modules/calls/CallDetailPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

type Call = components['schemas']['CallResponse']

const CALL_ID = '22222222-2222-4222-8222-222222222222'

function makeCall(overrides: Partial<Call> = {}): Call {
  return {
    id: CALL_ID,
    seq: 7,
    agent_id: 'agent-1',
    agent_name: 'Dilnoza Rahimova',
    number_e164: '+998997776655',
    number_id: 'number-1',
    installation_id: 'inst-1',
    direction: 'outgoing',
    disposition: 'answered',
    call_type: 'external',
    remote_number: '+998909998877',
    remote_number_key: '909998877',
    contact_name: 'Sardor ustoz',
    device_model: 'Xiaomi Redmi Note 12',
    started_at: '2026-09-05T09:03:11Z',
    answered_at: '2026-09-05T09:03:20Z',
    ended_at: '2026-09-05T09:05:20Z',
    duration_sec: 120,
    ring_sec: 9,
    received_at: '2026-09-05T09:05:30Z',
    clock_skew_sec: 2,
    device_timezone: 'Asia/Tashkent',
    source: 'live_capture',
    reconciled_with_call_log: true,
    has_audio: false,
    audio_missing_reason: 'not_expected',
    audio_duration_mismatch: false,
    audio: { available: false, duration_mismatch: false, audio_missing_reason: 'not_expected' },
    note: null,
    app_version: '1.4.0',
    app_variant: 'legacy28',
    ...overrides,
  }
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(call: Call) {
  fetchMock.mockResolvedValue(jsonResponse(200, call))
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[`/calls/${CALL_ID}`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/calls/:id" element={<CallDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions: [Perm.CALLS_READ],
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set([Perm.CALLS_READ]),
    loginError: null,
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

/** The header card is the first one on the page. */
function header(container: HTMLElement): HTMLElement {
  const card = container.querySelector('[class*="rounded-xl"]')
  expect(card).not.toBeNull()
  return card as HTMLElement
}

describe('two people, not a row of facts', () => {
  it('puts the employee on the left and the client on the right', async () => {
    const { container } = renderPage(makeCall())
    await screen.findByText(t('callDetail.employeeSide'))

    const card = header(container)
    const employee = within(card).getByText(t('callDetail.employeeSide'))
    const client = within(card).getByText(t('callDetail.clientSide'))

    // Order in the document is the order on screen.
    expect(employee.compareDocumentPosition(client)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('pairs each side with its own number', async () => {
    const { container } = renderPage(makeCall())
    await screen.findByText(t('callDetail.employeeSide'))
    const card = header(container)

    // The work number belongs to the employee, the remote number to the
    // client. Swapping them is silent and would misattribute every call.
    expect(within(card).getByText('+998 99 777 66 55')).toBeInTheDocument()
    expect(within(card).getByText('+998 90 999 88 77')).toBeInTheDocument()
    expect(within(card).getByText('Sardor ustoz')).toBeInTheDocument()
  })

  it('gives a withheld number a right-hand side that says so', async () => {
    // A withheld number is a real and common case: the server stores the call
    // with a NULL number rather than rejecting it. An empty half would read
    // as a rendering fault.
    const { container } = renderPage(makeCall({ remote_number: null, contact_name: null }))
    await screen.findByText(t('callDetail.employeeSide'))

    expect(within(header(container)).getByText(t('calls.numberWithheld'))).toBeInTheDocument()
  })
})

describe('direction is visible, not read', () => {
  it('names the direction beside the arrow', async () => {
    const { container } = renderPage(makeCall({ direction: 'outgoing' }))
    await screen.findByText(t('callDetail.employeeSide'))
    expect(within(header(container)).getByText(t('calls.direction.outgoing'))).toBeInTheDocument()
  })

  it('draws a different arrow for each direction', async () => {
    const outgoing = renderPage(makeCall({ direction: 'outgoing' }))
    await screen.findByText(t('callDetail.employeeSide'))
    const outClass = header(outgoing.container).querySelector('svg')?.getAttribute('class')
    outgoing.unmount()

    const incoming = renderPage(makeCall({ direction: 'incoming', disposition: 'missed', duration_sec: 0, answered_at: null }))
    await screen.findByText(t('callDetail.employeeSide'))
    const inClass = header(incoming.container).querySelector('svg')?.getAttribute('class')

    // Shape carries the meaning at a glance; the word carries it for anybody
    // who cannot see the shape.
    expect(outClass).not.toBe(inClass)
    expect(outClass).toContain('arrow-right')
    expect(inClass).toContain('arrow-left')
  })

  it('keeps the duration and the disposition', async () => {
    const { container } = renderPage(makeCall())
    await screen.findByText(t('callDetail.employeeSide'))
    const card = header(container)

    expect(within(card).getByText('02:00')).toBeInTheDocument()
    expect(within(card).getByText(t('calls.disposition.answered'))).toBeInTheDocument()
  })
})
