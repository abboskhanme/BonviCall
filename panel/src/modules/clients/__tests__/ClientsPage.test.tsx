/**
 * `/clients` — the page.
 *
 * What it must not get wrong, in order of how much damage it does:
 *
 *  1. one phone number written three ways must read as ONE customer — the
 *     server groups on the last-9 key, and the page must not undo that by
 *     keying rows on anything else;
 *  2. "Ko'tarmadi" is INCOMING and unanswered. An outgoing call the customer
 *     did not pick up is not the employee's fault, and the two must never be
 *     shown as one number (measured over a week: 983 and 1047);
 *  3. an unscored customer shows a dash and nothing else — a zero would read
 *     as "scored nought";
 *  4. a `sales` reader sees no agent filter, because the server has already
 *     narrowed the rows to their own customers.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ClientsPage } from '@/modules/clients/ClientsPage'
import { useAuth } from '@/modules/auth/store'
import { t } from '@/shared/i18n'
import { Perm } from '@/shared/auth/permissions'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function respond(handler: (url: string) => Response) {
  fetchMock.mockImplementation((input) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    return Promise.resolve(handler(url))
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'tester@bonvi.uz',
      full_name: 'Test User',
      role: 'manager',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function makeRow(overrides: Record<string, unknown> = {}) {
  return {
    phone_key: '901112233',
    name: 'Elyor aka',
    phone: '+998901112233',
    code: 'К00150',
    calls_total: 12,
    inbound: 5,
    outbound: 7,
    missed: 2,
    missed_rate: 40.0,
    talk_seconds: 3600,
    first_call_at: '2026-08-01T09:00:00Z',
    last_call_at: '2026-08-20T09:00:00Z',
    agent_count: 2,
    main_agent_id: '11111111-1111-4111-8111-111111111111',
    main_agent_name: 'Aziz',
    avg_score: 82.4,
    scored: 9,
    ...overrides,
  }
}

function makePage(items = [makeRow()], overrides: Record<string, unknown> = {}) {
  return {
    items,
    next_cursor: null,
    has_more: false,
    total: items.length,
    date_from: null,
    date_to: null,
    ...overrides,
  }
}

function serving(page: unknown = makePage()) {
  respond((url) => {
    if (url.includes('/agents')) {
      return jsonResponse(200, {
        items: [{ id: '11111111-1111-4111-8111-111111111111', full_name: 'Aziz' }],
      })
    }
    return jsonResponse(200, page)
  })
}

function renderPage(entry = '/clients') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ClientsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  signIn([Perm.CALLS_READ, Perm.AGENTS_READ])
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

// ── The three QueryBoundary states ────────────────────────────

describe('the three non-success states', () => {
  it('renders a skeleton while the directory is in flight', () => {
    respond(() => jsonResponse(200, makePage()))
    fetchMock.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('renders an error state when the request fails', async () => {
    respond(() =>
      jsonResponse(500, {
        error: { code: 'internal_error', message: 'x', request_id: 'r' },
      }),
    )
    renderPage()
    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
  })

  it('says "no customers yet" and "nothing matches" differently', async () => {
    serving(makePage([]))
    renderPage()
    expect(await screen.findByText(t('clients.emptyAll'))).toBeInTheDocument()

    serving(makePage([]))
    renderPage('/clients?search=zzz')
    expect(await screen.findByText(t('clients.emptyFiltered'))).toBeInTheDocument()
  })
})

// ── The row ───────────────────────────────────────────────────

describe('a customer row', () => {
  it('shows the name the uploaded phonebook gave, with its code', async () => {
    serving()
    renderPage()
    expect(await screen.findByText('Elyor aka')).toBeInTheDocument()
    expect(screen.getByText('К00150')).toBeInTheDocument()
  })

  it('falls back to the number when nobody has named it', async () => {
    serving(makePage([makeRow({ name: null, code: null, phone: null })]))
    renderPage()
    expect(await screen.findByText(t('clients.noName'))).toBeInTheDocument()
    expect(screen.getByText('901112233')).toBeInTheDocument()
  })

  it('keeps the incoming and outgoing counts apart', async () => {
    // ⚠️ THE MEASURED POINT. An unanswered incoming call is the company
    // failing to pick up; an unanswered outgoing one is a busy customer.
    // Adding them doubles the figure and destroys its meaning.
    serving(makePage([makeRow({ inbound: 5, outbound: 7, missed: 2 })]))
    renderPage()
    const row = (await screen.findByText('Elyor aka')).closest('tr')!
    expect(within(row).getByTitle(t('clients.inboundHint'))).toHaveTextContent('5')
    expect(within(row).getByTitle(t('clients.outboundHint'))).toHaveTextContent('7')
    expect(within(row).queryByText('12')).not.toBeNull() // calls_total, not 5+7
  })

  it('shows a dash and no number for an unscored customer', async () => {
    // A zero would read as "scored nought", and unscored rows are common
    // enough to fill the whole column with that lie.
    serving(makePage([makeRow({ avg_score: null, scored: 0 })]))
    renderPage()
    const row = (await screen.findByText('Elyor aka')).closest('tr')!
    expect(within(row).queryByText('0')).toBeNull()
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('marks how many OTHER employees have spoken to them', async () => {
    serving(makePage([makeRow({ agent_count: 3, main_agent_name: 'Aziz' })]))
    renderPage()
    expect(await screen.findByText('+2')).toBeInTheDocument()
  })

  it('links to the card by the phone key', async () => {
    serving()
    renderPage()
    const link = await screen.findByRole('link', { name: 'Elyor aka' })
    expect(link).toHaveAttribute('href', '/clients/901112233')
  })

  it('carries a non-default cut into the card link', async () => {
    // ⚠️ The server searches the `clients` cut by default, so an internal
    // number opened without it would rely on the card's own widening rule —
    // which works, but then the two screens disagree about which cut the
    // reader is in.
    serving()
    renderPage('/clients?scope=internal')
    const link = await screen.findByRole('link', { name: 'Elyor aka' })
    expect(link).toHaveAttribute('href', '/clients/901112233?scope=internal')
  })
})

// ── Scope ─────────────────────────────────────────────────────

describe('own scope', () => {
  it('hides the agent filter from a salesperson', async () => {
    signIn([Perm.CALLS_READ_OWN])
    serving()
    renderPage()
    await screen.findByText('Elyor aka')
    expect(screen.queryByLabelText(t('clients.filterAgent'))).toBeNull()
    expect(screen.queryByText(t('clients.filterAgentAll'))).toBeNull()
  })

  it('tells a salesperson why the list is short', async () => {
    signIn([Perm.CALLS_READ_OWN])
    serving()
    renderPage()
    expect(await screen.findByText(t('clients.ownScopeNote'))).toBeInTheDocument()
  })

  it('shows the agent column to a fleet-wide reader', async () => {
    serving()
    renderPage()
    // Scoped to the ROW: "Aziz" is also an option in the agent filter, and a
    // bare text query would pass on that alone even with the column gone.
    const row = (await screen.findByText('Elyor aka')).closest('tr')!
    expect(within(row).getByText('Aziz')).toBeInTheDocument()
  })
})

// ── Filters and the URL ───────────────────────────────────────

describe('the filter bar', () => {
  it('sends the search the URL carries', async () => {
    serving()
    renderPage('/clients?search=elyor')
    await screen.findByText('Elyor aka')
    const asked = fetchMock.mock.calls.map((call) => String(call[0])).join(' ')
    expect(asked).toContain('search=elyor')
  })

  it('asks for a total on the first page only', async () => {
    serving()
    renderPage()
    await screen.findByText('Elyor aka')
    const directory = fetchMock.mock.calls
      .map((call) => String(call[0]))
      .filter((url) => url.includes('/clients'))
    expect(directory.some((url) => url.includes('with_total=true'))).toBe(true)
  })

  it('drops the cursor when a filter changes', async () => {
    // Otherwise somebody on page five who narrows a filter is served an empty
    // table and reads it as "no data".
    serving()
    // A filter has to be in force for the reset button to exist at all —
    // which is itself the rule "a filter that is in force is a filter clear
    // removes".
    renderPage('/clients?search=elyor&cursor=abc')
    await screen.findByText('Elyor aka')

    await userEvent.click(screen.getByRole('button', { name: t('clients.filterReset') }))
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)?.[0] ?? '')
      expect(last).not.toContain('cursor=')
    })
  })
})
