/**
 * `/alerts` — the page where R3 and R17 become visible.
 *
 * An alert nobody acts on is worse than no alert, so what is pinned here is
 * actionability, not layout:
 *
 *  • the wording comes from `kind`, NOT from the server's `title_uz` — which
 *    is English today — and never from `body_uz`, which is the generic
 *    "contact the administrator";
 *  • every row carries a next action;
 *  • every row carries a way through to the thing that can fix it;
 *  • worst first, because the page is read top-down by somebody with an hour;
 *  • acknowledge is not rendered without `alerts:ack`.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AlertsPage } from '@/modules/alerts/AlertsPage'
import { ALERT_KIND_HINT, ALERT_KIND_LABEL } from '@/modules/alerts/labels'
import type { Alert } from '@/modules/alerts/api'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const AGENT_ID = 'agent-1'
const INSTALLATION_ID = 'inst-1'

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 'alert-1',
    kind: 'device_offline',
    severity: 'warning',
    // Exactly what the live server sends today: an English title and a body
    // that says nothing. The page must not lean on either.
    title_uz: 'Device offline',
    body_uz: 'Xatolik yuz berdi. Administratorga murojaat qiling.',
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
  it('names the problem from the kind, not from the English title_uz', async () => {
    world([makeAlert()])
    renderPage()

    expect(await screen.findByText(t(ALERT_KIND_LABEL.device_offline))).toBeInTheDocument()
    // The server's own strings are unusable today and the page must not show
    // them: one is English, the other says nothing at all.
    expect(screen.queryByText('Device offline')).toBeNull()
    expect(
      screen.queryByText('Xatolik yuz berdi. Administratorga murojaat qiling.'),
    ).toBeNull()
  })

  it('tells the reader what to do next', async () => {
    world([makeAlert()])
    renderPage()

    expect(await screen.findByText(t(ALERT_KIND_HINT.device_offline))).toBeInTheDocument()
    // A hint that merely restates the title would leave the page a list of
    // nouns, which is the failure this page exists to avoid.
    expect(t(ALERT_KIND_HINT.device_offline)).not.toBe(t(ALERT_KIND_LABEL.device_offline))
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
    world([makeAlert({ kind: 'retention_job_failed', agent_id: null, installation_id: null })])
    renderPage()

    await screen.findByText(t(ALERT_KIND_LABEL.retention_job_failed))
    expect(screen.queryByRole('link', { name: t('alerts.openDevice') })).toBeNull()
    expect(screen.queryByRole('link', { name: t('alerts.openAgent') })).toBeNull()
  })

  it('shows how long it has been going on rather than one row per repeat', async () => {
    world([makeAlert({ occurrence_count: 21 })])
    renderPage()

    expect(await screen.findByText(t('alerts.occurrences', { n: '21' }))).toBeInTheDocument()
    // 21 occurrences, one row.
    expect(screen.getAllByText(t(ALERT_KIND_LABEL.device_offline))).toHaveLength(1)
  })
})

describe('ordering', () => {
  it('puts the worst first', async () => {
    world([
      makeAlert({ id: 'info', kind: 'attribution_out_of_range', severity: 'info' }),
      makeAlert({ id: 'warn', kind: 'device_offline', severity: 'warning' }),
      makeAlert({ id: 'crit', kind: 'credential_replay', severity: 'critical' }),
    ])
    renderPage()

    // The order on screen, read as the page is read: top to bottom.
    const critical = await screen.findByText(t(ALERT_KIND_LABEL.credential_replay))
    const warning = screen.getByText(t(ALERT_KIND_LABEL.device_offline))
    const info = screen.getByText(t(ALERT_KIND_LABEL.attribution_out_of_range))

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

    await screen.findByText(t(ALERT_KIND_LABEL.device_offline))
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

    await screen.findByText(t(ALERT_KIND_LABEL.device_offline))
    const url = String(fetchMock.mock.calls.find(([i]) => String(i).includes('/alerts'))?.[0] ?? '')
    // The inbox is a to-do list, not an archive.
    expect(url).toContain('open_only=true')
  })

  it('scopes the detail line to technical values, and shows no secrets', async () => {
    world([makeAlert()])
    renderPage()

    const detail = await screen.findByText(/offline_minutes=10/)
    expect(within(detail).queryByText(/token/i)).toBeNull()
  })
})
