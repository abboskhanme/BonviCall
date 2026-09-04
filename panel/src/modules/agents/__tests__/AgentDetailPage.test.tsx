/**
 * `/agents/:id` — the page the rollout runs on.
 *
 * What is pinned here is the behaviour the page exists for, not its layout:
 *
 *  • the enrolment stage is shown as an INSTRUCTION, not a noun — an admin
 *    reading "permitted" learns nothing they can act on (R17);
 *  • the last failed attempt is surfaced with its timestamp, because the
 *    failure mode that makes R17 expensive is a salesperson who says nothing;
 *  • the assignment HISTORY is rendered, not just the current holder, because
 *    calls before a handover belong to the previous holder;
 *  • issuing a code is refused, in words, when the agent has no number;
 *  • controls the user lacks permission for are not rendered at all.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentDetailPage } from '@/modules/agents/AgentDetailPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const AGENT_ID = 'agent-1'
const NUMBER_ID = 'number-1'
const OLD_NUMBER_ID = 'number-0'

const agent = {
  id: AGENT_ID,
  full_name: 'Aziz Karimov',
  employee_code: 'BV-001',
  color: '#6366f1',
  hired_at: '2025-03-01',
  note: null,
  is_active: true,
  archived_at: null,
  created_at: '2025-03-01T00:00:00+05:00',
}

const numbers = {
  items: [
    {
      id: NUMBER_ID,
      e164: '+998901112233',
      phone_key: '901112233',
      operator: 'Beeline',
      sim_owner: 'company',
      label: null,
      is_active: true,
      created_at: '2025-03-01T00:00:00+05:00',
    },
    {
      id: OLD_NUMBER_ID,
      e164: '+998935554433',
      phone_key: '935554433',
      operator: 'Beeline',
      sim_owner: 'company',
      label: null,
      is_active: true,
      created_at: '2025-01-01T00:00:00+05:00',
    },
  ],
  total: 2,
}

/** Aziz holds one line now and held another until March — the case the
 *  time-boxed model exists for. */
const assignmentsByNumber: Record<string, unknown> = {
  [NUMBER_ID]: {
    items: [
      {
        id: 'assign-open',
        number_id: NUMBER_ID,
        agent_id: AGENT_ID,
        valid_from: '2026-03-01T00:00:00+05:00',
        valid_to: null,
        note: null,
        created_at: '2026-03-01T00:00:00+05:00',
      },
    ],
    total: 1,
  },
  [OLD_NUMBER_ID]: {
    items: [
      {
        id: 'assign-closed',
        number_id: OLD_NUMBER_ID,
        agent_id: AGENT_ID,
        valid_from: '2025-06-01T00:00:00+05:00',
        valid_to: '2026-03-01T00:00:00+05:00',
        note: 'raqam almashtirildi',
        created_at: '2025-06-01T00:00:00+05:00',
      },
    ],
    total: 1,
  },
}

function installations(stage: string) {
  return {
    items: [
      {
        id: 'inst-1',
        agent_id: AGENT_ID,
        number_id: NUMBER_ID,
        device_id: 'device-1',
        status: 'active',
        funnel_stage: stage,
        funnel_changed_at: '2026-09-05T09:00:00+05:00',
        created_at: '2026-09-01T00:00:00+05:00',
        verification_method: 'sim_msisdn',
        verified_at: '2026-09-01T00:00:00+05:00',
        attest_reason: null,
        bound_at: '2026-09-01T00:00:00+05:00',
        replaced_at: null,
        revoked_at: null,
        revoke_confirmed_at: null,
        revoke_pending_bytes: null,
        revoke_pending_records: null,
        app_version: '1.0.0',
        app_variant: 'modern34',
        sim_slot: 0,
        sim_subscription_id: 1,
      },
    ],
    total: 1,
  }
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface WorldOptions {
  stage?: string
  codes?: unknown[]
  attempts?: unknown[]
  receiverDown?: boolean
  noNumber?: boolean
}

function world(options: WorldOptions = {}) {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    const reply = (body: unknown) => Promise.resolve(jsonResponse(200, body))

    if (url.includes(`/api/v1/agents/${AGENT_ID}`)) return reply(agent)
    if (url.includes('/api/v1/agents')) return reply({ items: [agent], total: 1 })
    if (url.includes('/api/v1/numbers/') && url.includes('/assignments')) {
      const id = url.split('/numbers/')[1]?.split('/')[0] ?? ''
      if (options.noNumber) return reply({ items: [], total: 0 })
      return reply(assignmentsByNumber[id] ?? { items: [], total: 0 })
    }
    if (url.includes('/api/v1/numbers')) return reply(numbers)
    if (url.includes('/api/v1/installations')) return reply(installations(options.stage ?? 'permitted'))
    if (url.includes('/api/v1/devices')) return reply({ items: [], total: 0 })
    if (url.includes('/api/v1/enrolment-codes')) {
      return reply({ items: options.codes ?? [], total: (options.codes ?? []).length })
    }
    if (url.includes('/api/v1/enrolment/attempts')) {
      return reply({ items: options.attempts ?? [], total: (options.attempts ?? []).length })
    }
    if (url.includes('/api/v1/enrolment/receiver-status')) {
      return reply({
        enrolment_possible: !options.receiverDown,
        receiver_name: 'Receiver 1',
        receiver_msisdn: '+998901234567',
        status: options.receiverDown ? 'down' : 'up',
      })
    }
    return reply({})
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

const ADMIN = [
  Perm.AGENTS_READ,
  Perm.AGENTS_WRITE,
  Perm.AGENTS_ARCHIVE,
  Perm.NUMBERS_READ,
  Perm.NUMBERS_WRITE,
  Perm.ENROLMENT_READ,
  Perm.ENROLMENT_WRITE,
  Perm.INSTALLATIONS_READ,
  Perm.DEVICES_READ,
]

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[`/agents/${AGENT_ID}`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn(ADMIN)
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('enrolment progress', () => {
  it('tells the admin what to DO, not just which stage the agent is in', async () => {
    world({ stage: 'permitted' })
    renderPage()

    expect(await screen.findByText(t('funnel.hint.permitted'))).toBeInTheDocument()
    // The stage name alone — "Ruxsatlar berildi" — is a noun an admin cannot
    // act on. The hint is the whole point of this section.
    expect(t('funnel.hint.permitted')).not.toBe(t('funnel.permitted'))
  })

  it('surfaces the last failed attempt with its timestamp', async () => {
    world({
      stage: 'installed',
      attempts: [
        {
          id: 'attempt-1',
          kind: 'msisdn_check',
          outcome: 'msisdn_empty',
          step: null,
          created_at: '2026-09-05T09:30:00+05:00',
          agent_id: AGENT_ID,
          number_id: NUMBER_ID,
          installation_id: 'inst-1',
          device_model: 'Xiaomi Redmi 10C',
          app_version: '1.0.0',
          duration_ms: 900,
        },
      ],
    })
    renderPage()

    // "They say it will not work" — at which step, and when.
    expect(await screen.findByText(t('enrolOutcome.msisdn_empty'))).toBeInTheDocument()
    expect(screen.getByText(t('enrol.lastFailure'))).toBeInTheDocument()
    expect(screen.getByText(/05\/09\/2026/)).toBeInTheDocument()
  })

  it('warns that nobody can enrol while the callback receiver is down', async () => {
    world({ receiverDown: true })
    renderPage()

    // Absence of enrolment must be an event, not a quiet stall: the banner
    // appears before anyone wastes a code.
    expect(await screen.findByText(t('enrol.receiverDown'))).toBeInTheDocument()
  })

  it('stays silent about the receiver when enrolment is possible', async () => {
    world({ receiverDown: false })
    renderPage()

    await screen.findByText(t('enrol.title'))
    expect(screen.queryByText(t('enrol.receiverDown'))).toBeNull()
  })

  it('explains that a code needs a number, rather than offering a dead button', async () => {
    world({ noNumber: true })
    renderPage()

    expect(await screen.findByText(t('enrol.needsNumber'))).toBeInTheDocument()
  })
})

describe('the time-boxed number assignment', () => {
  it('shows the line they hold now AND the one they used to hold', async () => {
    world()
    renderPage()

    expect(await screen.findByText('+998 90 111 22 33')).toBeInTheDocument()
    // The history is not decoration: calls made before the March handover are
    // still this agent's, and nothing else in the panel says so.
    expect(screen.getByText(t('numbers.historyTitle'))).toBeInTheDocument()
    expect(screen.getByText(t('numbers.historyHint'))).toBeInTheDocument()
    expect(screen.getByText('+998 93 555 44 33')).toBeInTheDocument()
  })

  it('marks only the open assignment as held now', async () => {
    world()
    renderPage()

    await screen.findByText('+998 90 111 22 33')
    expect(screen.getAllByText(t('numbers.holdsNow'))).toHaveLength(1)
  })
})

describe('permissions', () => {
  it('renders no write control for a reader who holds only the read permissions', async () => {
    signIn([Perm.AGENTS_READ, Perm.NUMBERS_READ, Perm.ENROLMENT_READ, Perm.INSTALLATIONS_READ])
    world()
    renderPage()

    await screen.findByText(t('enrol.title'))
    // A control the user cannot use is not rendered at all (CONVENTIONS.md
    // §11) — the server still decides, but the panel shows no locked doors.
    expect(screen.queryByRole('button', { name: t('agents.edit') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('agents.archive') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('numbers.assign') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('enrol.issue') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('enrol.reissue') })).toBeNull()
  })

  it('offers the code button to a holder of enrolment:write', async () => {
    world()
    renderPage()

    const section = (await screen.findByText(t('enrol.title'))).closest('div')
    expect(section).toBeTruthy()
    expect(await screen.findByRole('button', { name: t('enrol.issue') })).toBeInTheDocument()
  })

  it('hides the whole enrolment section from somebody without enrolment:read', async () => {
    signIn([Perm.AGENTS_READ, Perm.NUMBERS_READ])
    world()
    renderPage()

    expect(await screen.findByText('Aziz Karimov')).toBeInTheDocument()
    expect(screen.queryByText(t('enrol.title'))).toBeNull()
  })
})

describe('states', () => {
  it('renders the error state with its Uzbek sentence', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(404, { error: { code: 'not_found', message: 'Not Found' } }),
    )
    renderPage()

    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
    expect(screen.getByText(t('errors.not_found'))).toBeInTheDocument()
    expect(screen.queryByText('Not Found')).toBeNull()
  })

  it('renders the loading state before anything arrives', () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('says the agent has no device rather than showing an empty box', async () => {
    world()
    renderPage()

    const heading = await screen.findByText(t('agentDetail.deviceTitle'))
    const section = heading.closest('div')?.parentElement?.parentElement
    expect(section).toBeTruthy()
    expect(within(section as HTMLElement).getByText(t('agentDetail.noDevice'))).toBeInTheDocument()
  })
})
