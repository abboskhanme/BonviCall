/**
 * `/activity` — the page.
 *
 * What it must not get wrong, in order of how much damage it does:
 *
 *  1. the two "unanswered" figures must never be shown as one — an incoming
 *     call nobody answered is the company's fault and an outgoing one is not
 *     (measured over a week: 983 and 1047);
 *  2. the headline counts CUSTOMERS, not events — repeat attempts by one
 *     person are one person;
 *  3. a `sales` reader sees no agent filter, because the server has already
 *     narrowed the rows to their own;
 *  4. the detail dialog is reachable only where there is something to show,
 *     and it reconciles with the row that opened it.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ActivityPage } from '@/modules/activity/ActivityPage'
import { t } from '@/shared/i18n'
import { useAuth } from '@/modules/auth/store'
import { tokenStore } from '@/shared/api/client'
import { Perm } from '@/shared/auth/permissions'

import { AZIZ, makeMissedClients, makeReport, makeRow } from './fixtures'

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

function renderPage(entry = '/activity') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ActivityPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The report, the roster and the detail list, each on its own path. */
function serving(report = makeReport(), clients = makeMissedClients()) {
  respond((url) => {
    if (url.includes('/activity/missed-clients')) return jsonResponse(200, clients)
    if (url.includes('/activity')) return jsonResponse(200, report)
    if (url.includes('/agents')) {
      return jsonResponse(200, {
        items: [
          { id: AZIZ, full_name: 'Aziz' },
          { id: '22222222-2222-4222-8222-222222222222', full_name: 'Dilnoza' },
        ],
        total: 2,
      })
    }
    return jsonResponse(404, { error: { code: 'not_found', message: '', request_id: '' } })
  })
  return renderPage()
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.CALLS_READ, Perm.AGENTS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('the two kinds of unanswered call', () => {
  /**
   * ⚠️ THE POINT OF THE REPORT. "Xodim ko'tarmadi" is the company failing to
   * pick up; "Mijoz ko'tarmadi" is a customer who was busy. One column would be
   * twice the figure and none of the meaning.
   */
  it('gives them separate columns with separate names', async () => {
    serving()

    const table = await screen.findByRole('table')
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((header) => header.textContent)
    expect(headers.some((header) => header?.includes(t('activity.colMissed')))).toBe(true)
    expect(headers.some((header) => header?.includes(t('activity.colOutNoAnswer')))).toBe(true)
    expect(t('activity.colMissed')).not.toBe(t('activity.colOutNoAnswer'))
  })

  it('shows the company totals as four separate cards', async () => {
    serving()

    // By role and not by text: three of the four cards share their wording
    // with a column of the table below — the same metric shown twice, on
    // purpose — so a bare text query matches two elements and passes or fails
    // for the wrong reason.
    expect(await screen.findByRole('group', { name: t('activity.outbound') })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: t('activity.inbound') })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: t('activity.missed') })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: t('activity.unreached') })).toBeInTheDocument()
  })
})

describe('customers, not events', () => {
  /**
   * The headline is measured in PEOPLE. A customer who cannot get through tries
   * again — 1.8 times on average — and counting events counts one person's
   * problem several times.
   */
  it('leads with the number of customers nobody called back', async () => {
    serving(
      makeReport({
        // Nine missed EVENTS from four people, three of whom were never
        // contacted. The card must say three.
        total: makeRow({
          agent_id: '00000000-0000-0000-0000-000000000000',
          agent_name: '',
          missed: 9,
          missed_clients: 4,
          clients_reached: 1,
          clients_unreached: 3,
        }),
      }),
    )

    // Located by its own hint line, which is unique on the page: the figure
    // itself is a bare number and there are several of those.
    const hint = await screen.findByText(t('activity.unreachedHint', { hours: 24 }))
    const card = hint.parentElement as HTMLElement
    expect(within(card).getByText('3')).toBeInTheDocument()
  })

  it('explains the callback window in the headline card', async () => {
    serving()
    expect(
      await screen.findByText(t('activity.unreachedHint', { hours: 24 })),
    ).toBeInTheDocument()
  })

  /** Medians cannot be averaged, so the report's own value is shown. */
  it('states the company median beside the cards', async () => {
    serving()
    expect(
      await screen.findByText(t('activity.medianNote', { minutes: 11.4, hours: 24 })),
    ).toBeInTheDocument()
  })
})

describe('scope', () => {
  it('offers the agent filter to a reader who can see everybody', async () => {
    serving()
    expect(await screen.findByText(t('activity.byAgent'))).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  /**
   * `calls:read:own` is a salesperson. The SERVER narrows the rows; this page
   * only hides a filter that would be one repeated name — presentation, not
   * access control.
   */
  it('hides it from a reader who only sees their own row', async () => {
    signIn([Perm.CALLS_READ_OWN])
    serving(makeReport({ agents: [makeRow()] }))

    expect(await screen.findByText(t('activity.myRow'))).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText(t('activity.ownScopeNote'))).toBeInTheDocument()
  })
})

describe('the window', () => {
  it('puts the chosen period in the URL, so the view can be linked', async () => {
    serving()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: t('activity.period.d30') }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes('days=30'))).toBe(
        true,
      ),
    )
  })

  /** An explicit range WINS over `days` on the server, so pressing a period
   *  button must clear it — otherwise nothing changes and the reader reads
   *  that as a fault. */
  it('clears an explicit range when a period button is pressed', async () => {
    serving()
    renderPage('/activity?date_from=2026-08-01&date_to=2026-08-10')
    await screen.findAllByRole('table')

    await userEvent.click(screen.getAllByRole('button', { name: t('activity.period.d7') })[0]!)
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)?.[0] ?? '')
      expect(last.includes('date_from')).toBe(false)
    })
  })

  /** One day of daily bars is a single point and says nothing; the hourly cut
   *  is where "customers cannot get through at lunchtime" becomes visible. */
  it('switches the chart to hours when the window is a single day', async () => {
    serving(makeReport({ days: 1 }))
    expect(await screen.findByText(t('activity.chartTitleHour'))).toBeInTheDocument()
    expect(screen.queryByText(t('activity.chartTitle'))).toBeNull()
  })

  it('draws days for anything longer', async () => {
    serving()
    expect(await screen.findByText(t('activity.chartTitle'))).toBeInTheDocument()
  })
})

describe('the table', () => {
  it('sorts on a column, descending first', async () => {
    serving()
    const table = await screen.findByRole('table')

    // Scoped to the table: the chart legend carries the same four labels.
    await userEvent.click(
      within(table).getByRole('button', { name: new RegExp(t('activity.colMissed')) }),
    )

    const body = within(table)
      .getAllByRole('row')
      .filter((row) => within(row).queryAllByRole('cell').length > 0)
    // Aziz has 6 missed, Dilnoza 0 — so Aziz comes first descending.
    expect(within(body[0]!).getAllByRole('cell')[0]?.textContent).toContain('Aziz')
  })

  it('closes with a total row once there is more than one employee', async () => {
    serving()
    expect(await screen.findByText(t('activity.totalRow'))).toBeInTheDocument()
  })

  it('explains a column when its header is pressed', async () => {
    serving()
    await screen.findByRole('table')
    expect(screen.getByText(t('activity.byAgentHint'))).toBeInTheDocument()

    // The whole accessible name, not a substring: "Mijoz" is also the opening
    // word of "Mijoz ko'tarmadi", so a loose match picks two headers and the
    // click lands on whichever the DOM happens to order first.
    await userEvent.click(
      within(screen.getByRole('table')).getByRole('button', {
        name: t('activity.colClients'),
      }),
    )
    expect(await screen.findByText(t('activity.tipClients'))).toBeInTheDocument()
  })
})

describe('the detail dialog', () => {
  it('opens from a row that has unreached customers and proves its number', async () => {
    serving()
    const table = await screen.findByRole('table')

    // Scoped: the agent filter lists the same names.
    await userEvent.click(within(table).getByText('Aziz'))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Aziz')).toBeInTheDocument()
    // Two customers, three attempts between them, one still unreached.
    expect(
      within(dialog).getByText(
        t('activity.drillTotals', { clients: 2, attempts: 5, unreached: 1 }),
      ),
    ).toBeInTheDocument()
  })

  it('names who made contact, and which way round', async () => {
    serving()
    const table = await screen.findByRole('table')
    await userEvent.click(within(table).getByText('Aziz'))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Dilnoza/)).toBeInTheDocument()
    expect(within(dialog).getByText(t('activity.drillNotReached'))).toBeInTheDocument()
  })

  /** An employee with no unreached customers has nothing to show, so there is
   *  no way in either. */
  it('stays shut for a row with nothing behind it', async () => {
    serving()
    const table = await screen.findByRole('table')

    await userEvent.click(within(table).getByText('Dilnoza'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('the export button', () => {
  it('is offered once the report has arrived', async () => {
    serving()
    const button = await screen.findByRole('button', { name: t('activity.export.button') })
    await waitFor(() => expect(button).not.toBeDisabled())
  })

  /** An empty file is indistinguishable from a broken button. */
  it('is disabled while there is nothing to write', async () => {
    respond(() => jsonResponse(200, makeReport({ agents: [] })))
    renderPage()
    const button = await screen.findByRole('button', { name: t('activity.export.button') })
    expect(button).toBeDisabled()
  })
})

describe('the three QueryBoundary states', () => {
  it('renders the skeleton before the response arrives', async () => {
    let release: ((response: Response) => void) | undefined
    // Only the REPORT is held open. The roster answers at once, or the last
    // promise created — the roster's — would be the one this test releases.
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/agents')) return Promise.resolve(jsonResponse(200, { items: [], total: 0 }))
      return new Promise<Response>((resolve) => {
        release = resolve
      })
    })

    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
    release?.(jsonResponse(200, makeReport()))
    await waitFor(() => expect(screen.queryByTestId('query-loading')).toBeNull())
  })

  it('renders an error code from the envelope as its Uzbek sentence', async () => {
    respond(() =>
      jsonResponse(403, {
        error: { code: 'forbidden', message: 'Forbidden', request_id: '01J9' },
      }),
    )

    renderPage()

    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
    expect(screen.queryByText('Forbidden')).toBeNull()
  })

  /** "No employees in this window" is its own sentence, not the generic one
   *  (SPEC §5.3). */
  it('says so in its own words when there is nobody in the window', async () => {
    respond(() => jsonResponse(200, makeReport({ agents: [] })))
    renderPage()

    expect(await screen.findByTestId('query-empty')).toBeInTheDocument()
    expect(screen.getByText(t('activity.emptyTitle'))).toBeInTheDocument()
  })
})
