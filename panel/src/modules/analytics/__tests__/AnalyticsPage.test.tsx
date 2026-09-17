/**
 * `/analytics` — the analysis dashboard.
 *
 * The five things it must not get wrong:
 *
 *  1. the KPI row shows what the server sent, and the **breaches** card reads a
 *     rise as bad news rather than green;
 *  2. the call-type strip is present whenever the scored count is smaller than
 *     the total — without it "128" in a month of 1,420 reads as lost data;
 *  3. the window in the header is the SERVER's resolved one, not the browser's
 *     idea of "last 30 days";
 *  4. every filter goes into the URL and therefore into the next request, all
 *     six queries at once;
 *  5. the agent filter is not offered to somebody who cannot read the roster.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 *
 * The charts themselves are not asserted on: Recharts measures its container,
 * jsdom has no layout, and what could be *wrong* about them is the arithmetic
 * in `chart.ts`, which has its own test. A ResizeObserver stub is installed
 * below so the components mount rather than throw.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalyticsPage } from '@/modules/analytics/AnalyticsPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

import {
  makeBlocks,
  makeDistribution,
  makeOverview,
  makeRanking,
  makeRedFlags,
  makeTimeseries,
} from './fixtures'

const fetchMock = vi.fn<typeof fetch>()

/** jsdom has no layout engine and therefore no ResizeObserver; Recharts'
 *  ResponsiveContainer asks for one the moment it mounts. */
class StubResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Every request the page makes, in the order it made them. */
const requested: string[] = []

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  return input instanceof URL ? input.toString() : input.url
}

/** Route by path, so one handler serves all seven of the page's queries. */
function respondWithReports(overrides: Record<string, unknown> = {}) {
  const bodies: Record<string, unknown> = {
    '/analytics/overview': makeOverview(),
    '/analytics/timeseries': makeTimeseries(),
    '/analytics/agents': makeRanking(),
    '/analytics/blocks': makeBlocks(),
    '/analytics/red-flags': makeRedFlags(),
    '/analytics/distribution': makeDistribution(),
    '/agents': { items: [{ id: 'a1', full_name: 'Anvar Karimov' }], total: 1 },
    ...overrides,
  }
  fetchMock.mockImplementation((input) => {
    const url = urlOf(input)
    requested.push(url)
    const match = Object.keys(bodies).find((path) => url.includes(path))
    return Promise.resolve(jsonResponse(200, match ? bodies[match] : {}))
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'tester@bonvi.uz',
      full_name: 'Test Manager',
      role: 'manager',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function renderPage(entry = '/analytics') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AnalyticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The query string of the last request to `path`. */
function lastQuery(path: string): URLSearchParams {
  const url = [...requested].reverse().find((candidate) => candidate.includes(path))
  return new URLSearchParams((url ?? '').split('?')[1] ?? '')
}

beforeEach(() => {
  requested.length = 0
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('ResizeObserver', StubResizeObserver)
  tokenStore.set('test-token')
  signIn([Perm.ANALYSIS_READ, Perm.AGENTS_READ, Perm.CALLS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('the KPI row', () => {
  it('shows the four headline numbers the server sent', async () => {
    respondWithReports()
    renderPage()

    expect(await screen.findByText('128')).toBeInTheDocument()
    expect(screen.getByText('78.4')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    // 187 seconds, formatted as every duration in the panel is.
    expect(screen.getByText('03:07')).toBeInTheDocument()
  })

  it('reads a rise in breaches as bad news, not as growth', async () => {
    respondWithReports()
    renderPage()

    // Both cards carry a delta; the calls one rose 12.5 % and is good, the
    // breaches one rose 50 % and is not. Without `invertDelta` the second
    // would be green in the week somebody shouted at four customers.
    const good = await screen.findByText('+12.5%')
    const bad = screen.getByText('+50.0%')
    expect(good.className).toContain('text-good')
    expect(bad.className).toContain('text-bad')
  })

  /**
   * The line that stops the headline reading as lost data: the KPI counts
   * SCORED conversations, and an internal call is never a candidate. Measured
   * in BonviZvonki: 72 scored against 22,026 calls in one period.
   */
  it('explains the scored count with the whole period beside it', async () => {
    respondWithReports()
    renderPage()

    expect(
      await screen.findByText(t('analytics.kpiCallsHint', { total: '1 420' })),
    ).toBeInTheDocument()
    expect(screen.getByText(t('analytics.byType', { count: '1 420' }))).toBeInTheDocument()
    expect(screen.getByText('1 100')).toBeInTheDocument()
  })

  it('says nothing about the whole period when every call was scored', async () => {
    respondWithReports({
      '/analytics/overview': makeOverview({
        calls: { value: 12, delta_percent: null },
        calls_total: 12,
        call_types: { internal: 0, external: 12, unknown: 0 },
      }),
    })
    renderPage()

    // Two elements read "12" here — the KPI and the call-type strip's own
    // count — which is itself the case under test: the hint is what would say
    // they differ, and it must not be rendered when they do not.
    await screen.findAllByText('12')
    expect(screen.queryByText(t('analytics.kpiCallsHint', { total: '12' }))).toBeNull()
  })
})

describe('the window', () => {
  /**
   * The server resolves "last 30 days" in Asia/Tashkent and echoes the two
   * dates back. A caption computed here from the browser's clock would name a
   * period the numbers were not measured over.
   */
  it('captions the page with the window the server resolved', async () => {
    respondWithReports()
    renderPage()

    expect(
      await screen.findByText(
        t('analytics.window', { from: '01/06/2026', to: '30/06/2026' }),
      ),
    ).toBeInTheDocument()
  })
})

describe('the filters', () => {
  it('sends the window and the filters from the URL on every report', async () => {
    respondWithReports()
    renderPage('/analytics?days=7&call_type=external&agent_id=a1')

    await screen.findByText('128')

    for (const path of [
      '/analytics/overview',
      '/analytics/timeseries',
      '/analytics/agents',
      '/analytics/blocks',
      '/analytics/red-flags',
      '/analytics/distribution',
    ]) {
      const query = lastQuery(path)
      expect(query.get('days'), path).toBe('7')
      expect(query.get('call_type'), path).toBe('external')
      // A repeated parameter, never a comma-joined string: the server declares
      // `list[UUID]` and would answer 422.
      expect(query.getAll('agent_id'), path).toEqual(['a1'])
    }
  })

  it('puts a chosen period in the URL, so the page is a link', async () => {
    respondWithReports()
    renderPage()
    await screen.findByText('128')

    await userEvent.click(screen.getByRole('button', { name: t('analytics.period7') }))

    await waitFor(() => expect(lastQuery('/analytics/overview').get('days')).toBe('7'))
  })

  it('only sends the bucket to the trend, never to the other five', async () => {
    respondWithReports()
    renderPage()
    await screen.findByText('128')

    await userEvent.click(screen.getByRole('button', { name: t('analytics.bucketWeek') }))

    await waitFor(() =>
      expect(lastQuery('/analytics/timeseries').get('bucket')).toBe('week'),
    )
    expect(lastQuery('/analytics/overview').get('bucket')).toBeNull()
  })

  it('ignores a filter value the server would refuse', async () => {
    respondWithReports()
    renderPage('/analytics?call_type=nearly&bucket=hourly')
    await screen.findByText('128')

    // A pasted value that is not in the enum is no filter at all, rather than a
    // 422 the reader cannot act on.
    expect(lastQuery('/analytics/overview').get('call_type')).toBeNull()
    expect(lastQuery('/analytics/timeseries').get('bucket')).toBe('day')
  })

  it('does not offer the agent filter to somebody who cannot read the roster', async () => {
    signIn([Perm.ANALYSIS_READ])
    respondWithReports()
    renderPage()

    await screen.findByText('128')
    expect(screen.queryByLabelText(t('analytics.filterAgent'))).toBeNull()
    // The roster endpoint, not the analytics one: `/analytics/agents` also
    // ends in "/agents".
    expect(requested.some((url) => /\/api\/v1\/agents\?/.test(url))).toBe(false)
  })
})

describe('the leaderboard', () => {
  it('renders the rows in the order the server ranked them', async () => {
    respondWithReports()
    renderPage()

    const table = await screen.findByRole('table')
    const names = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[1]?.textContent)
    expect(names).toEqual(['Anvar Karimov', 'Zafar Tursunov'])
    expect(within(table).getByText('88.2')).toBeInTheDocument()
  })

  /**
   * `null` is not zero: an agent who scored nothing last period has no place to
   * have gained, and "unchanged" would claim a rank they never held.
   */
  it('leaves the movement blank for an agent new to the period', async () => {
    respondWithReports()
    renderPage()

    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    const climber = rows[0]
    const newcomer = rows[1]
    // Two places gained, drawn as an arrow and a number.
    expect(climber && within(climber).getAllByRole('cell')[6]?.textContent).toBe('2')
    // No previous rank at all: an em dash, never "unchanged".
    expect(newcomer && within(newcomer).getAllByRole('cell')[6]?.textContent).toBe('—')
  })
})

describe('the three QueryBoundary states', () => {
  it('renders skeletons before the responses arrive', () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    renderPage()

    expect(screen.getAllByTestId('query-loading').length).toBeGreaterThan(0)
  })

  it('renders an error code from the envelope as its Uzbek sentence', async () => {
    fetchMock.mockImplementation((input) => {
      requested.push(urlOf(input))
      return Promise.resolve(
        jsonResponse(403, {
          error: { code: 'forbidden', message: 'Forbidden', request_id: '01J9' },
        }),
      )
    })
    renderPage()

    expect((await screen.findAllByTestId('query-error')).length).toBeGreaterThan(0)
    expect(screen.getAllByText(t('errors.forbidden')).length).toBeGreaterThan(0)
    expect(screen.queryByText('Forbidden')).toBeNull()
  })

  /**
   * Three different sentences, never one generic line (SPEC §5.3). "Nothing was
   * scored in this period" and "no breach was found" are not the same news, and
   * the second one is good.
   */
  it('names the empty case for each card', async () => {
    respondWithReports({
      '/analytics/agents': makeRanking({ items: [], total: 0 }),
      '/analytics/blocks': makeBlocks({ items: [] }),
      '/analytics/red-flags': makeRedFlags({ items: [], total: 0 }),
      '/analytics/distribution': makeDistribution({
        scored_calls: 0,
        items: makeDistribution().items.map((item) => ({ ...item, calls: 0 })),
      }),
    })
    renderPage()

    expect(await screen.findByText(t('analytics.emptyFlags'))).toBeInTheDocument()
    expect(screen.getByText(t('analytics.emptyFlagsHint'))).toBeInTheDocument()
    expect(screen.getAllByText(t('analytics.emptyScores')).length).toBe(3)
  })
})
