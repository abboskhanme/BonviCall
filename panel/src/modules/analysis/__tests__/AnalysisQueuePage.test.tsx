/**
 * `/analysis/queue` — the operational page (§7.5).
 *
 * The four things it must not get wrong:
 *
 *  1. with `analysis.enabled` false — the state a live BonviCall is in today —
 *     six zeroes are CORRECT, and the page says so instead of looking broken;
 *  2. `priced: false` never renders as "$0.00": a cost of zero because nobody
 *     typed a vendor price is not a free feature (§11.1);
 *  3. `waiting_retry` stays apart from `stages.failed` — one of them needs a
 *     person and the other does not;
 *  4. the retry button is `analysis:run` only.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalysisQueuePage } from '@/modules/analysis/AnalysisQueuePage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

import { CALL_ID, makeState, makeStatus, type AnalysisStatus } from './fixtures'

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function respond(handler: (url: string, init?: RequestInit) => Response) {
  fetchMock.mockImplementation((input, init) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    return Promise.resolve(handler(url, init))
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/analysis/queue']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AnalysisQueuePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function showing(status: AnalysisStatus) {
  respond(() => jsonResponse(200, status))
  return renderPage()
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.ANALYSIS_READ, Perm.ANALYSIS_RUN])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('what is waiting', () => {
  it('renders one tile per stage, with the counts the server sent', async () => {
    showing(makeStatus())

    expect(await screen.findByText(t('analysis.stage.queued'))).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('431')).toBeInTheDocument()
    // `skipped` is a visible number and not an error: 88 calls that were never
    // candidates is a fact, not a fault (§2.4).
    expect(screen.getByText(t('analysis.stage.skipped'))).toBeInTheDocument()
    expect(screen.getByText('88')).toBeInTheDocument()
  })

  /**
   * Kept apart from `stages.failed` on purpose: one of them needs a person and
   * the other does not. Merging them is how 885 rate-limited calls stayed
   * "permanently failed" in BonviZvonki after the quota had already reset.
   */
  it('keeps "waiting to retry" separate from "failed"', async () => {
    showing(makeStatus())

    expect(await screen.findByText(t('analysis.waitingRetry'))).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    expect(screen.getByText(t('analysis.waitingRetryHint'))).toBeInTheDocument()
  })

  it('shows why calls are being skipped, by reason', async () => {
    showing(makeStatus())

    // "412 calls are waiting on the line directory" must be visible rather than
    // silent (§2.6).
    expect(await screen.findByText(t('analysis.failure.call_type_unknown'))).toBeInTheDocument()
    expect(screen.getByText('412')).toBeInTheDocument()
  })

  it('says the normal thing when no provider is sitting out', async () => {
    showing(makeStatus())

    expect(await screen.findByText(t('analysis.cooldownEmpty'))).toBeInTheDocument()
  })

  it('names the role and the reason when one is', async () => {
    showing(
      makeStatus({
        cooldowns: [
          {
            role: 'asr',
            seconds_left: 1420,
            reason_code: 'provider_rate_limit',
            started_at: '2026-09-15T10:00:00+05:00',
            until_at: '2026-09-15T10:24:00+05:00',
            detail: 'quota resets at midnight UTC',
          },
        ],
      }),
    )

    // A daily quota and a 503 read very differently, so the reason is shown
    // beside the role rather than folded into "unavailable".
    expect(await screen.findByText(t('analysis.role.asr'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.failure.provider_rate_limit'))).toBeInTheDocument()
  })
})

describe('the feature flag', () => {
  /**
   * `analysis.enabled` is seeded false, so on a live system every number on
   * this page is zero and that is the correct answer. Without this banner the
   * page reads as broken — and "why has nothing been scored since Tuesday" is
   * the exact question it exists to answer.
   */
  it('leads with the flag when the module is off', async () => {
    showing(
      makeStatus({
        enabled: false,
        stages: { queued: 0, transcribing: 0, scoring: 0, completed: 0, skipped: 0, failed: 0 },
        waiting_retry: 0,
        not_analysable: [],
      }),
    )

    expect(await screen.findByText(t('analysis.disabledTitle'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.queueDisabledHint'))).toBeInTheDocument()
    // The counts are still shown: zero IS the answer, and hiding it would hide
    // the very thing somebody came to check.
    expect(screen.getByText(t('analysis.stage.queued'))).toBeInTheDocument()
  })

  it('says nothing about the flag when the module is on', async () => {
    showing(makeStatus())

    await screen.findByText(t('analysis.waitingRetry'))
    expect(screen.queryByText(t('analysis.disabledTitle'))).toBeNull()
  })
})

describe('the month, and the $0.00 that must never appear', () => {
  it('refuses to print a cost while no vendor price has been entered', async () => {
    showing(makeStatus())

    expect(await screen.findByText(t('analysis.monthNotPriced'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.monthNotPricedHint'))).toBeInTheDocument()
    // The number that would tell a client the feature is free.
    expect(screen.queryByText('$0.00')).toBeNull()
    // The cap that actually protects the account until then IS shown.
    expect(
      screen.getByText(t('analysis.ofCap', { used: '431', cap: '3 000' })),
    ).toBeInTheDocument()
  })

  it('prints the spend against the cap once a price exists', async () => {
    const base = makeStatus()
    showing({
      ...base,
      month: { ...base.month, priced: true, cost_micro_usd: 12_340_000 },
    })

    expect(
      await screen.findByText(t('analysis.ofCap', { used: '$12.34', cap: '$50.00' })),
    ).toBeInTheDocument()
    expect(screen.queryByText(t('analysis.monthNotPriced'))).toBeNull()
  })
})

describe('recent failures', () => {
  const FAILURE = {
    call_id: CALL_ID,
    started_at: '2026-09-15T10:12:00+05:00',
    stage: 'transcribe',
    code: 'provider_network' as const,
    detail: 'connection reset by peer',
    attempts: 3,
    last_run_at: '2026-09-15T10:30:00+05:00',
  }

  it('says the normal thing when nothing broke', async () => {
    showing(makeStatus())
    expect(await screen.findByText(t('analysis.failuresEmpty'))).toBeInTheDocument()
  })

  it('gives each failure its reason, its half and a way to act on it', async () => {
    showing(makeStatus({ recent_failures: [FAILURE] }))

    const table = await screen.findByRole('table')
    expect(within(table).getByText(t('analysis.failure.provider_network'))).toBeInTheDocument()
    expect(within(table).getByText(t('analysis.half.transcribe'))).toBeInTheDocument()
    expect(within(table).getByText('connection reset by peer')).toBeInTheDocument()
    expect(
      within(table).getByRole('button', { name: t('analysis.retryButton') }),
    ).toBeInTheDocument()
  })

  it('queues the call again through the same endpoint the detail page uses', async () => {
    const posts: string[] = []
    respond((url, init) => {
      if (init?.method === 'POST') {
        posts.push(url)
        return jsonResponse(200, makeState({ stage: 'queued' }))
      }
      return jsonResponse(200, makeStatus({ recent_failures: [FAILURE] }))
    })

    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: t('analysis.retryButton') }))

    await waitFor(() => expect(posts.length).toBe(1))
    expect(posts[0]).toContain(`/api/v1/analysis/calls/${CALL_ID}`)
  })

  it('hides the retry from a reader who may not spend money', async () => {
    // `manager` reads the queue and cannot re-run anything on it (§6.1).
    signIn([Perm.ANALYSIS_READ])
    showing(makeStatus({ recent_failures: [FAILURE] }))

    await screen.findByRole('table')
    expect(screen.queryByRole('button', { name: t('analysis.retryButton') })).toBeNull()
  })
})

describe('the three QueryBoundary states', () => {
  it('renders the skeleton before the response arrives', async () => {
    let release: ((response: Response) => void) | undefined
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { release = resolve }))

    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
    release?.(jsonResponse(200, makeStatus()))
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
    expect(screen.getByText(t('errors.forbidden'))).toBeInTheDocument()
    expect(screen.queryByText('Forbidden')).toBeNull()
  })

  /**
   * No `isEmpty` on this page, deliberately: six zeroes and a flag that is off
   * IS the answer somebody came for, and a generic "nothing here" box would
   * hide exactly that.
   */
  it('never collapses an all-zero queue into a generic empty box', async () => {
    showing(
      makeStatus({
        enabled: false,
        stages: { queued: 0, transcribing: 0, scoring: 0, completed: 0, skipped: 0, failed: 0 },
        waiting_retry: 0,
        not_analysable: [],
      }),
    )

    await screen.findByText(t('analysis.disabledTitle'))
    expect(screen.queryByTestId('query-empty')).toBeNull()
  })
})
