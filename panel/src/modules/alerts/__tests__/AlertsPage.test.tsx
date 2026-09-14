/**
 * `/alerts` — the page where R3 and R17 become visible.
 *
 * An alert nobody acts on is worse than no alert, so what is pinned here is
 * actionability, not layout:
 *
 *  • the wording comes from the server's `title_uz` / `body_uz`, which are
 *    derived from `kind` out of this panel's own former catalogue — the two
 *    cannot disagree because there is now only one copy;
 *  • every row carries a next action;
 *  • every row carries a way through to the thing that can fix it;
 *  • worst first, because the page is read top-down by somebody with an hour;
 *  • acknowledge is not rendered without `alerts:ack`.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AlertsPage } from '@/modules/alerts/AlertsPage'
import { isFirstObservation } from '@/modules/alerts/routing'
import type { Alert } from '@/modules/alerts/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const AGENT_ID = 'agent-1'
const INSTALLATION_ID = 'inst-1'

/** Stand-ins for the server-derived wording. Opaque on purpose (§14). */
const TITLE = 'server-derived-title'
const BODY = 'server-derived-body'
const OTHER_TITLE = 'another-server-derived-title'

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 'alert-1',
    kind: 'device_offline',
    severity: 'warning',
    // Opaque tokens, not Uzbek: these stand in for whatever sentence the
    // server derived from `kind`, and §14 keeps Uzbek out of a .tsx. The same
    // convention `shared/api/__tests__/client.test.ts` uses for `message`.
    title_uz: TITLE,
    body_uz: BODY,
    agent_id: AGENT_ID,
    installation_id: INSTALLATION_ID,
    number_id: 'number-1',
    device_model: 'Xiaomi Redmi 10C',
    first_seen_at: '2026-09-05T08:00:00+05:00',
    last_seen_at: '2026-09-05T09:00:00+05:00',
    occurrence_count: 21,
    acknowledged_at: null,
    acknowledged_by: null,
    resolved_at: null,
    detail: { offline_minutes: 10, never_reported: false },
    ...overrides,
  }
}

const agents = {
  items: [
    {
      id: AGENT_ID,
      full_name: 'Aziz Karimov',
      employee_code: 'BV-001',
      color: '#6366f1',
      hired_at: null,
      note: null,
      is_active: true,
      archived_at: null,
      created_at: '2025-01-01T00:00:00+05:00',
    },
  ],
  total: 1,
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function world(alerts: Alert[]) {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/api/v1/agents')) return Promise.resolve(jsonResponse(200, agents))
    if (url.includes('/api/v1/alerts')) {
      return Promise.resolve(jsonResponse(200, { items: alerts, total: alerts.length }))
    }
    return Promise.resolve(jsonResponse(200, {}))
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

function renderPage(path = '/alerts') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/alerts" element={<AlertsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.ALERTS_READ, Perm.ALERTS_ACK, Perm.AGENTS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('an alert somebody can act on', () => {
  it('renders the server-derived title', async () => {
    world([makeAlert()])
    renderPage()

    expect(await screen.findByText(TITLE)).toBeInTheDocument()
  })

  it('tells the reader what to do next', async () => {
    world([makeAlert()])
    renderPage()

    // Without a next action the page is a list of nouns, which is the failure
    // it exists to avoid.
    expect(await screen.findByText(BODY)).toBeInTheDocument()
  })

  it('says an already-broken phone never LOST the permission', async () => {
    // A handset that arrived with the permission denied never lost it, and
    // wording that asserts a change sends an admin hunting for one that never
    // happened.
    world([
      makeAlert({
        kind: 'permission_lost_microphone',
        title_uz: OTHER_TITLE,
        body_uz: BODY,
        detail: { capability: 'microphone', to: 'denied', first_observation: true },
      }),
    ])
    renderPage()

    expect(await screen.findByText(t('alerts.firstObservation'))).toBeInTheDocument()
  })

  it('says nothing of the sort for a real transition', async () => {
    world([
      makeAlert({
        kind: 'permission_lost_microphone',
        title_uz: OTHER_TITLE,
        body_uz: BODY,
        detail: { capability: 'microphone', from: 'granted_working', to: 'denied' },
      }),
    ])
    renderPage()

    await screen.findByText(OTHER_TITLE)
    expect(screen.queryByText(t('alerts.firstObservation'))).toBeNull()
  })

  it('says who it is about and links to them', async () => {
    world([makeAlert()])
    renderPage()

    const name = await screen.findByRole('link', { name: 'Aziz Karimov' })
    expect(name).toHaveAttribute('href', `/agents/${AGENT_ID}`)
  })

  it('links a device problem to the device that has it', async () => {
    world([makeAlert({ kind: 'battery_optimisation_reenabled' })])
    renderPage()

    const link = await screen.findByRole('link', { name: t('alerts.openDevice') })
    expect(link).toHaveAttribute('href', `/devices/${INSTALLATION_ID}`)
  })

  it('links an enrolment problem to the agent, not to a phone', async () => {
    // `enrolment_stalled` is fixed on the agent's card; a link to a handset
    // would be a dead end.
    world([makeAlert({ kind: 'enrolment_stalled' })])
    renderPage()

    expect(await screen.findByRole('link', { name: t('alerts.openAgent') })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: t('alerts.openDevice') })).toBeNull()
  })

  it('offers no link at all for a server-side problem', async () => {
    // Nothing on a phone fixes a failed retention job.
    world([
      makeAlert({
        kind: 'retention_job_failed',
        agent_id: null,
        installation_id: null,
        title_uz: OTHER_TITLE,
      }),
    ])
    renderPage()

    await screen.findByText(OTHER_TITLE)
    expect(screen.queryByRole('link', { name: t('alerts.openDevice') })).toBeNull()
    expect(screen.queryByRole('link', { name: t('alerts.openAgent') })).toBeNull()
  })

  it('shows how long it has been going on rather than one row per repeat', async () => {
    world([makeAlert({ occurrence_count: 21 })])
    renderPage()

    expect(await screen.findByText(t('alerts.occurrences', { n: '21' }))).toBeInTheDocument()
    // 21 occurrences, one row.
    expect(screen.getAllByText(TITLE)).toHaveLength(1)
  })
})

describe('ordering', () => {
  it('puts the worst first', async () => {
    world([
      makeAlert({ id: 'info', kind: 'attribution_out_of_range', severity: 'info', title_uz: 'info-title' }),
      makeAlert({ id: 'warn', kind: 'device_offline', severity: 'warning' }),
      makeAlert({ id: 'crit', kind: 'credential_replay', severity: 'critical', title_uz: 'critical-title' }),
    ])
    renderPage()

    // The order on screen, read as the page is read: top to bottom.
    const critical = await screen.findByText('critical-title')
    const warning = screen.getByText(TITLE)
    const info = screen.getByText('info-title')

    expect(critical.compareDocumentPosition(warning)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(warning.compareDocumentPosition(info)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  it('calls out the critical count above the list', async () => {
    world([makeAlert({ kind: 'credential_replay', severity: 'critical' })])
    renderPage()

    expect(await screen.findByText(t('alerts.criticalCount', { n: 1 }))).toBeInTheDocument()
  })
})

describe('permissions and states', () => {
  it('does not render acknowledge without alerts:ack', async () => {
    signIn([Perm.ALERTS_READ])
    world([makeAlert()])
    renderPage()

    await screen.findByText(TITLE)
    expect(screen.queryByRole('button', { name: t('alerts.acknowledge') })).toBeNull()
  })

  it('acknowledges through the server rather than hiding the row locally', async () => {
    world([makeAlert()])
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: t('alerts.acknowledge') }))

    const posted = fetchMock.mock.calls.find(
      ([input, init]) => String(input).includes('/ack') && init?.method === 'POST',
    )
    expect(posted).toBeDefined()
  })

  it('reads "nothing is wrong" as good news, not as an empty grey box', async () => {
    world([])
    renderPage()

    expect(await screen.findByText(t('alerts.emptyAll'))).toBeInTheDocument()
  })

  it('renders the error state in Uzbek', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(403, { error: { code: 'forbidden', message: 'Forbidden' } }),
    )
    renderPage()

    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
    expect(screen.getByText(t('errors.forbidden'))).toBeInTheDocument()
  })

  it('renders the loading state', () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    renderPage()
    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('shows only open alerts by default', async () => {
    world([makeAlert()])
    renderPage()

    await screen.findByText(TITLE)
    const url = String(fetchMock.mock.calls.find(([i]) => String(i).includes('/alerts'))?.[0] ?? '')
    // The inbox is a to-do list, not an archive.
    expect(url).toContain('open_only=true')
  })

  it('never prints the machine-readable detail on the page', async () => {
    /** It used to, and it read as a program fault rather than a phone fault.
     *
     *  The field still arrives and still decides what the row says — the
     *  first-observation sentence below is driven by it — so this pins the
     *  screen, not the response. Re-adding the line is a one-line change and
     *  would look like an improvement to whoever made it. */
    world([makeAlert()])
    renderPage()

    await screen.findByText(TITLE)
    expect(screen.queryByText(/offline_minutes/)).toBeNull()
    expect(screen.queryByText(/never_reported/)).toBeNull()
    expect(screen.queryByText(/=/)).toBeNull()
  })
})

describe('isFirstObservation', () => {
  it('recognises the flag whichever way it is spelled', () => {
    // The flag is landing separately from the alerts that already carry
    // from/to, so both spellings are accepted rather than one guessed at.
    expect(isFirstObservation({ first_observation: true })).toBe(true)
    expect(isFirstObservation({ first_seen: true })).toBe(true)
  })

  it('treats an absent or unknown prior state as a first observation', () => {
    expect(isFirstObservation({ to: 'denied', from: null })).toBe(true)
    expect(isFirstObservation({ to: 'denied', from: 'unknown' })).toBe(true)
  })

  it('leaves a real transition alone', () => {
    expect(isFirstObservation({ from: 'granted_working', to: 'denied' })).toBe(false)
    expect(isFirstObservation({ offline_minutes: 10 })).toBe(false)
    expect(isFirstObservation(null)).toBe(false)
  })
})
