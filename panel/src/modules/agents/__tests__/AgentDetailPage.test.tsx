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
 *  time-boxed model exists for. One request answers both (`GET /assignments
 *  ?agent_id=`), which replaced a fan-out over every registered number. */
const agentAssignments = {
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
  total: 2,
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

/** One phone, as `/devices` reports it. Only the fields this page reads. */
function health(installationId: string, overrides: Record<string, unknown> = {}) {
  return {
    installation_id: installationId,
    agent_id: AGENT_ID,
    number_id: NUMBER_ID,
    manufacturer: 'Xiaomi',
    model: `Redmi ${installationId}`,
    android_release: '13',
    api_level: 33,
    app_version: '1.0.7',
    app_variant: 'legacy28',
    battery_percent: 80,
    battery_charging: false,
    battery_optimisation_exempt: true,
    capturing: true,
    recording_route: 'oem_file_harvest',
    recording_route_ok: true,
    last_heartbeat_at: '2026-09-14T09:00:00+05:00',
    last_call_at: null,
    queue_pending: 0,
    queue_bytes: null,
    never_reported: false,
    installation_status: 'active',
    bound_at: '2026-09-01T00:00:00+05:00',
    created_at: '2026-09-01T00:00:00+05:00',
    ...overrides,
  }
}

/** One installation row, as `/installations` reports it. `created_at` is the
 *  field the page orders by, so it is what the caller sets. */
function installationRow(id: string, createdAt: string, overrides: Record<string, unknown> = {}) {
  return { ...installations('permitted').items[0], id, created_at: createdAt, ...overrides }
}

interface WorldOptions {
  stage?: string
  codes?: unknown[]
  attempts?: unknown[]
  receiverDown?: boolean
  noNumber?: boolean
  devices?: unknown[]
  installationItems?: unknown[]
}

function world(options: WorldOptions = {}) {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    const reply = (body: unknown) => Promise.resolve(jsonResponse(200, body))

    if (url.includes(`/api/v1/agents/${AGENT_ID}`)) return reply(agent)
    if (url.includes('/api/v1/agents')) return reply({ items: [agent], total: 1 })
    if (url.includes('/api/v1/assignments')) {
      return reply(options.noNumber ? { items: [], total: 0 } : agentAssignments)
    }
    if (url.includes('/api/v1/numbers')) return reply(numbers)
    if (url.includes('/api/v1/installations')) {
      const items = options.installationItems
      return reply(
        items
          ? { items, total: items.length }
          : installations(options.stage ?? 'permitted'),
      )
    }
    if (url.includes('/api/v1/devices')) {
      const items = options.devices ?? []
      return reply({ items, total: items.length })
    }
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
    // The stage name alone is a noun an admin cannot act on; the hint is a
    // sentence they can. Asserting they DIFFER is what stops somebody
    // "simplifying" the hint into a copy of the label.
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

describe('one phone, not the whole history of phones', () => {
  /**
   * A rollout retries. One agent on the live fleet had twenty installations,
   * and every one of them used to render a card here — long enough to hide
   * the only row anybody opens this page for.
   */
  const THREE_PHONES: WorldOptions = {
    installationItems: [
      installationRow('inst-old', '2026-08-01T00:00:00+05:00'),
      installationRow('inst-new', '2026-09-10T00:00:00+05:00'),
      installationRow('inst-mid', '2026-09-01T00:00:00+05:00'),
    ],
    devices: [health('inst-old'), health('inst-new'), health('inst-mid')],
  }

  it('shows the newest installation and no other', async () => {
    world(THREE_PHONES)
    renderPage()

    expect(await screen.findByText('Xiaomi Redmi inst-new')).toBeInTheDocument()
    expect(screen.queryByText('Xiaomi Redmi inst-old')).toBeNull()
    expect(screen.queryByText('Xiaomi Redmi inst-mid')).toBeNull()
  })

  it('counts the older ones rather than discarding them silently', async () => {
    world(THREE_PHONES)
    renderPage()

    expect(
      await screen.findByText(t('agentDetail.olderDevices', { n: 2 })),
    ).toBeInTheDocument()
  })

  it('says nothing about older phones when there is only one', async () => {
    world({
      installationItems: [installationRow('inst-1', '2026-09-01T00:00:00+05:00')],
      devices: [health('inst-1')],
    })
    renderPage()

    expect(await screen.findByText('Xiaomi Redmi inst-1')).toBeInTheDocument()
    expect(screen.queryByText(/eski qurilma/)).toBeNull()
  })

  it('prefers the newest over the ACTIVE one', async () => {
    /** The distinction this page has already paid for once: an old verified
     *  installation outranks the handset that is stuck at a permission screen
     *  this morning, so "active" shows the wrong phone exactly when somebody
     *  is looking for the right one. */
    world({
      installationItems: [
        installationRow('inst-old', '2026-08-01T00:00:00+05:00', { status: 'active' }),
        installationRow('inst-new', '2026-09-10T00:00:00+05:00', { status: 'pending' }),
      ],
      devices: [
        health('inst-old', { installation_status: 'active' }),
        health('inst-new', { installation_status: 'pending', never_reported: true, last_heartbeat_at: null }),
      ],
    })
    renderPage()

    expect(await screen.findByText('Xiaomi Redmi inst-new')).toBeInTheDocument()
    expect(screen.queryByText('Xiaomi Redmi inst-old')).toBeNull()
  })
})

describe('one enrolment code', () => {
  function code(id: string, createdAt: string, overrides: Record<string, unknown> = {}) {
    return {
      id,
      code: id.toUpperCase(),
      number_id: NUMBER_ID,
      agent_id: AGENT_ID,
      created_at: createdAt,
      expires_at: '2026-12-31T00:00:00+05:00',
      redeemed_at: null,
      revoked_at: null,
      attempt_count: 0,
      ...overrides,
    }
  }

  it('shows the live code and not the ones it replaced', async () => {
    world({
      codes: [
        code('k7m4pq01', '2026-09-01T00:00:00+05:00', { redeemed_at: '2026-09-02T00:00:00+05:00' }),
        code('k7m4pq02', '2026-09-10T00:00:00+05:00'),
      ],
    })
    renderPage()

    expect(await screen.findByText('K7M4PQ02')).toBeInTheDocument()
    expect(screen.queryByText('K7M4PQ01')).toBeNull()
    expect(screen.getByText(t('enrol.olderCodes', { n: 1 }))).toBeInTheDocument()
  })

  it('falls back to the newest when none is live', async () => {
    /** A dead code is still worth showing — it carries when it was issued and
     *  what happened to it. Showing nothing would read as "no code was ever
     *  given", which is a different and wrong answer. */
    world({
      codes: [
        code('k7m4pq03', '2026-09-10T00:00:00+05:00', { revoked_at: '2026-09-11T00:00:00+05:00' }),
      ],
    })
    renderPage()

    expect(await screen.findByText('K7M4PQ03')).toBeInTheDocument()
  })
})

describe('what the card no longer says', () => {
  it('shows neither a hire date nor a note', async () => {
    /** Removed at the client's request on 2026-09-14. This card is opened to
     *  answer "is this person's phone capturing", and neither fact was ever
     *  part of that. Pinned because re-adding a Field looks like an
     *  improvement to whoever does it. */
    world()
    renderPage()

    await screen.findByText('Aziz Karimov')
    expect(screen.queryByText('01.03.2025')).toBeNull()
    expect(screen.queryByText(/Ishga kirgan/i)).toBeNull()
    expect(screen.queryByText(/^Izoh$/)).toBeNull()
  })
})
