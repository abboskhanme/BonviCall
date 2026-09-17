/**
 * `/surveys` — the page.
 *
 * What it must not get wrong, in order of how much damage it does:
 *
 *  1. an average that is not ready is never drawn as a number, and never as
 *     `0` — one customer's bad morning must not become a published score;
 *  2. the threshold comes from the RESPONSE, so an admin who sets 8 sees 8;
 *  3. a salesperson's withheld rows are explained, not rendered as an empty
 *     list that reads "nobody has ever rated you";
 *  4. the misconduct labels come from the server, never from this module.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '@/modules/auth/store'
import { SurveysPage } from '@/modules/surveys/SurveysPage'
import { tokenStore } from '@/shared/api/client'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'

import { makeCollecting, makeFeedback, makeWithheld, RED_FLAGS } from './fixtures'

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

type Role = 'admin' | 'manager' | 'sales'

function signIn(permissions: string[], role: Role = 'manager', agentId: string | null = null) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'tester@bonvi.uz',
      full_name: 'Test User',
      role,
      permissions,
      must_change_password: false,
      agent_id: agentId,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/surveys']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <SurveysPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function serving(report = makeFeedback()) {
  respond((url) => {
    if (url.includes('/surveys/red-flags')) return jsonResponse(200, RED_FLAGS)
    if (url.includes('/surveys')) return jsonResponse(200, report)
    if (url.includes('/agents')) {
      return jsonResponse(200, { items: [], total: 0 })
    }
    return jsonResponse(404, { error: { code: 'not_found', message: '', request_id: '' } })
  })
  return renderPage()
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.ANALYSIS_READ, Perm.AGENTS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
  useAuth.setState({ status: 'anonymous', user: null, permissions: new Set(), loginError: null })
})

describe('the three query states', () => {
  it('renders the loading skeleton first', () => {
    respond(() => jsonResponse(200, makeFeedback()))
    renderPage()
    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
  })

  it('renders the error state and offers a retry', async () => {
    respond(() =>
      jsonResponse(500, {
        error: { code: 'internal_error', message: 'xatolik', request_id: 'r1' },
      }),
    )
    renderPage()
    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
  })

  it('renders the success branch', async () => {
    serving()
    expect(await screen.findByText(t('surveys.feedbackTitle'))).toBeInTheDocument()
  })
})

describe('the average is withheld until it means something', () => {
  it('shows the count out of the threshold and no number', async () => {
    serving(makeCollecting())
    // "3 / 8" — the progress, not an em dash and not a 0.
    expect(
      await screen.findByText(t('surveys.collecting', { count: 3, min: 8 })),
    ).toBeInTheDocument()
    // The denominator is on screen. `getAllByText` because the threshold is
    // deliberately said twice — once as the tile's "3 / 8" and once in the
    // sentence below it that explains what is still needed.
    expect(screen.getAllByText(/\/\s*8/).length).toBeGreaterThan(0)
    // 4.6 is the READY fixture's average; it must not appear here.
    expect(screen.queryByText('4.60')).not.toBeInTheDocument()
  })

  it('reads the threshold from the response and not from a constant', async () => {
    // ⚠️ The defect the source's own comment records: an admin sets 8, the
    // code keeps comparing against a hard-coded 5, and the setting "looks
    // like it works" while affecting nothing.
    serving(makeCollecting())
    expect(
      await screen.findByText(t('surveys.collecting', { count: 3, min: 8 })),
    ).toBeInTheDocument()
  })

  it('shows the average once it is ready', async () => {
    serving()
    expect(await screen.findByText('4.60')).toBeInTheDocument()
  })

  it('says how many more answers are needed', async () => {
    serving(makeCollecting())
    expect(
      await screen.findByText(t('surveys.notReadyRemaining', { count: 5, min: 8 })),
    ).toBeInTheDocument()
  })
})

describe('the response rate distinguishes null from zero', () => {
  it('shows a dash and the "nothing sent" hint when there is no denominator', async () => {
    // ⚠️ In THIS deployment nothing is ever sent — there is no bot — so this
    // is the permanent state of the figure. "0 %" would read as "every
    // customer ignored us".
    serving(makeCollecting())
    expect(await screen.findByText(t('surveys.responseRateNone'))).toBeInTheDocument()
  })

  it('shows a percentage when surveys were sent', async () => {
    serving()
    expect(await screen.findByText('62.5%')).toBeInTheDocument()
  })
})

describe('a salesperson', () => {
  beforeEach(() => {
    signIn([Perm.CALLS_READ_OWN], 'sales', '99999999-9999-4999-8999-999999999999')
  })

  it('is told the rows are withheld rather than shown an empty list', async () => {
    // ⚠️ One group is one customer, so one visible row identifies who wrote
    // it. An unexplained empty list reads as "nobody has ever rated you".
    serving(makeWithheld())
    expect(await screen.findByText(t('surveys.itemsWithheld'))).toBeInTheDocument()
  })

  it('sees their own title and no agent filter', async () => {
    serving(makeWithheld())
    expect(await screen.findByText(t('surveys.myTitle'))).toBeInTheDocument()
    expect(screen.queryByText(t('surveys.allAgents'))).not.toBeInTheDocument()
  })

  it('gets an explanation, not an error card, when the section is closed', async () => {
    respond(() =>
      jsonResponse(403, {
        error: { code: 'forbidden', message: 'yopiq', request_id: 'r1' },
      }),
    )
    renderPage()
    expect(await screen.findByText(t('surveys.forbidden'))).toBeInTheDocument()
    expect(screen.queryByTestId('query-error')).not.toBeInTheDocument()
  })
})

describe('the misconduct registry comes from the server', () => {
  it('renders the label the server sent, not one held in this module', async () => {
    serving()
    expect(await screen.findByTitle('Juda kech javob berdi')).toBeInTheDocument()
  })

  it('falls back to the key when no label has arrived', async () => {
    respond((url) => {
      if (url.includes('/surveys/red-flags')) return jsonResponse(500, {})
      if (url.includes('/surveys')) return jsonResponse(200, makeFeedback())
      return jsonResponse(200, { items: [], total: 0 })
    })
    renderPage()
    // The chip stays and shows the raw key; it does not vanish.
    expect(await screen.findByTitle('late_reply')).toBeInTheDocument()
  })
})

describe('the comment dialog', () => {
  it('opens on a card and shows the full comment', async () => {
    serving()
    const user = userEvent.setup()
    await screen.findByText(t('surveys.feedbackTitle'))
    await user.click(screen.getByText('Kech javob berdi'))
    await waitFor(() =>
      expect(screen.getByText(t('surveys.commentTitle'))).toBeInTheDocument(),
    )
  })
})
