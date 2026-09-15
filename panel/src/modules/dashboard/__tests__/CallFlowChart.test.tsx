/**
 * The call-flow chart, and the two promises it makes to a reader:
 *
 *   1. the period control governs the WHOLE dashboard, not just the chart —
 *      the tiles that count calls move with it (that is why it lives in the
 *      page header and the window comes from one response);
 *   2. what is drawn links to the calls it was drawn from, so a line nobody
 *      believes can be checked against the list in one click (SPEC §5.2).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DashboardPage } from '@/modules/dashboard/DashboardPage'
import { useAuth } from '@/modules/auth/store'
import { CALL_CLASS_LABEL } from '@/modules/calls/labels'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A week whose middle day is busy, so a flat line would be visible as a bug. */
function weekStats(period: string) {
  const days = ['2026-09-09', '2026-09-10', '2026-09-11']
  return {
    period,
    granularity: 'day',
    date_from: days[0],
    date_to: days[days.length - 1],
    buckets: days.map((day, index) => ({
      date_from: day,
      date_to: day,
      incoming_answered: index === 1 ? 4 : 0,
      outgoing_answered: index === 1 ? 3 : 1,
      missed: index === 1 ? 2 : 0,
      rejected: 0,
      no_answer: 1,
      total: index === 1 ? 9 : 2,
    })),
  }
}

function world() {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/api/v1/calls/stats')) {
      const period = new URL(url, 'http://localhost').searchParams.get('period') ?? 'week'
      return Promise.resolve(jsonResponse(weekStats(period)))
    }
    if (url.includes('/api/v1/reports/gap')) {
      return Promise.resolve(
        jsonResponse({
          answered_calls: 10,
          calls_with_audio: 8,
          missing_total: 2,
          capture_rate: '80.00',
          by_reason: [],
          by_model: [],
          by_agent: [],
          open_deltas: [],
        }),
      )
    }
    return Promise.resolve(jsonResponse({ items: [], total: 0, next_cursor: null, has_more: false }))
  })
}

function signIn(permissions: readonly string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions: [...permissions],
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

/** Where the router went, so a click-through is checkable. */
function Probe() {
  const location = useLocation()
  return <span data-testid="location">{`${location.pathname}${location.search}`}</span>
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/dashboard']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <DashboardPage />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  world()
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

function statsRequests(): string[] {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.includes('/calls/stats'))
}

describe('the period control', () => {
  it('re-asks the server when the reader picks a different window', async () => {
    signIn([Perm.CALLS_READ, Perm.REPORTS_READ])
    renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))

    await userEvent.click(screen.getByRole('button', { name: t('dashboard.chart.period.year') }))

    await waitFor(() => {
      expect(statsRequests().some((url) => url.includes('period=year'))).toBe(true)
    })
  })

  it('asks once for a window two cards and a chart are all reading', async () => {
    // The tile, the capture rate and the chart must not each compute their own
    // fortnight — they share one response, so they cannot disagree.
    signIn([Perm.CALLS_READ, Perm.REPORTS_READ])
    renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))

    await waitFor(() => expect(statsRequests()).toHaveLength(1))
    // The capture rate re-asks once the window lands: until then it is the
    // unfiltered report, which is a true answer to a wider question rather
    // than a guessed fortnight.
    await waitFor(() => {
      const gap = fetchMock.mock.calls
        .map(([input]) => String(input))
        .filter((url) => url.includes('/reports/gap'))
        .at(-1)
      expect(gap).toContain('date_from=2026-09-09')
      expect(gap).toContain('date_to=2026-09-11')
    })
  })
})

describe('a range the reader picks themselves', () => {
  async function chooseCustom() {
    await userEvent.click(screen.getByRole('button', { name: t('dashboard.chart.period.custom') }))
  }

  it('asks for nothing until both ends are chosen', async () => {
    signIn([Perm.CALLS_READ])
    renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))
    const before = statsRequests().length

    await chooseCustom()
    await userEvent.type(screen.getByLabelText(t('calls.filterDateFrom')), '2026-09-01')

    // One date is half a question. Asking would be a 400 on every keystroke.
    expect(screen.getByText(t('dashboard.chart.pickBothDates'))).toBeInTheDocument()
    expect(statsRequests().filter((url) => url.includes('period=custom'))).toHaveLength(0)
    expect(statsRequests().length).toBe(before)
  })

  it('sends both dates once they are, and puts them in the URL', async () => {
    signIn([Perm.CALLS_READ])
    renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))

    await chooseCustom()
    await userEvent.type(screen.getByLabelText(t('calls.filterDateFrom')), '2026-09-01')
    await userEvent.type(screen.getByLabelText(t('calls.filterDateTo')), '2026-09-11')

    await waitFor(() => {
      const url = statsRequests().find((request) => request.includes('period=custom'))
      expect(url).toContain('date_from=2026-09-01')
      expect(url).toContain('date_to=2026-09-11')
    })
    // The fields keep what was typed, because the value they render comes back
    // out of the URL rather than out of local state.
    expect(screen.getByLabelText(t('calls.filterDateFrom'))).toHaveValue('2026-09-01')
  })

  it('drops the dates when a preset is chosen again', async () => {
    signIn([Perm.CALLS_READ])
    renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))

    await chooseCustom()
    await userEvent.type(screen.getByLabelText(t('calls.filterDateFrom')), '2026-09-01')
    await userEvent.type(screen.getByLabelText(t('calls.filterDateTo')), '2026-09-11')
    await userEvent.click(screen.getByRole('button', { name: t('dashboard.chart.period.month') }))

    await waitFor(() => {
      const last = statsRequests().at(-1)
      expect(last).toContain('period=month')
      // A preset carrying dates is a link whose label lies.
      expect(last).not.toContain('date_from')
    })
    expect(screen.queryByLabelText(t('calls.filterDateFrom'))).not.toBeInTheDocument()
  })
})

describe('the chart itself', () => {
  it('draws one line per class of call (UC-11)', async () => {
    signIn([Perm.CALLS_READ])
    const { container } = renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))

    await waitFor(() => {
      expect(container.querySelectorAll('svg[role="img"] path')).toHaveLength(5)
    })
  })

  it('names every line and gives each one its total for the period', async () => {
    signIn([Perm.CALLS_READ])
    renderDashboard()
    const legend = await screen.findByRole('button', {
      name: new RegExp(t(CALL_CLASS_LABEL.incoming_answered)),
    })
    // 0 + 4 + 0 across the three days.
    expect(within(legend).getByText('4')).toBeInTheDocument()
  })

  it('hides a line the reader switches off, and keeps the last one on', async () => {
    signIn([Perm.CALLS_READ])
    const { container } = renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))
    await waitFor(() => expect(container.querySelectorAll('svg[role="img"] path')).toHaveLength(5))

    for (const key of Object.values(CALL_CLASS_LABEL)) {
      await userEvent.click(screen.getByRole('button', { name: new RegExp(t(key)) }))
    }

    // An empty plot area is indistinguishable from a broken one, so the fifth
    // click does nothing.
    expect(container.querySelectorAll('svg[role="img"] path')).toHaveLength(1)
  })

  it('opens the calls behind the point that was clicked', async () => {
    // Not the point a previous `mousemove` left behind — on a touchscreen
    // there is no `mousemove` at all.
    signIn([Perm.CALLS_READ])
    const { container } = renderDashboard()
    await screen.findByText(t('dashboard.chart.title'))
    const plot = await waitFor(() => {
      const svg = container.querySelector('svg[role="img"]')
      expect(svg).not.toBeNull()
      return svg as SVGSVGElement
    })

    plot.getBoundingClientRect = () => ({ left: 0, width: 800 }) as DOMRect
    // The far right of the plot is the last bucket, whatever was hovered.
    fireEvent.click(plot, { clientX: 780 })

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe(
        '/calls?date_from=2026-09-11&date_to=2026-09-11',
      )
    })
  })

  it('says the period is quiet rather than drawing nothing and leaving it there', async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/v1/calls/stats')) {
        return Promise.resolve(
          jsonResponse({
            period: 'week',
            granularity: 'day',
            date_from: '2026-09-09',
            date_to: '2026-09-09',
            buckets: [
              {
                date_from: '2026-09-09',
                date_to: '2026-09-09',
                incoming_answered: 0,
                outgoing_answered: 0,
                missed: 0,
                rejected: 0,
                no_answer: 0,
                total: 0,
              },
            ],
          }),
        )
      }
      return Promise.resolve(jsonResponse({ items: [], total: 0 }))
    })
    signIn([Perm.CALLS_READ])
    renderDashboard()

    expect(await screen.findByText(t('dashboard.chart.silent'))).toBeInTheDocument()
  })
})
