/**
 * `/analysis/:callId` — the seven states of §7.4, rendered.
 *
 * `state.test.ts` pins the precedence RULE; this file pins what each row of it
 * actually puts on screen, because a correct rule wired to the wrong branch is
 * the same bug with a longer stack trace. Four rows in particular:
 *
 *   flag off + no state   one sentence and NOTHING else
 *   no state row          the invitation and the button
 *   failed                the Uzbek headline, the retry, the raw detail
 *   completed             the score and the transcript
 *
 * Plus the two rendering rules the port found the hard way: no zero bar for a
 * block nobody was assessed on, and a header that reads "60 / 75".
 *
 * And the permission split of §6.1: a `manager` sees the section and not the
 * button, an `admin` sees both.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalysisDetailPage } from '@/modules/analysis/AnalysisDetailPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

import {
  CALL_ID,
  makeCallAnalysis,
  makeScoreWithNaBlock,
  makeState,
  type CallAnalysis,
} from './fixtures'

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
        initialEntries={[`/analysis/${CALL_ID}`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/analysis/:callId" element={<AnalysisDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Render the page against one `GET /analysis/calls/{id}` answer. */
function showing(data: CallAnalysis) {
  respond(() => jsonResponse(200, data))
  return renderPage()
}

function runButton(): HTMLElement | null {
  return screen.queryByRole('button', { name: t('analysis.runButton') })
}

function retryButton(): HTMLElement | null {
  return screen.queryByRole('button', { name: t('analysis.retryButton') })
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

describe('row 1 — the flag is off and nothing was ever analysed', () => {
  /**
   * "Tahlil o'chirilgan" **and nothing else**: a disabled feature does not
   * advertise itself. This is the state a live BonviCall is in today, because
   * `analysis.enabled` is seeded false.
   */
  it('says only that the module is off', async () => {
    showing(
      makeCallAnalysis({ enabled: false, state: null, score: null, transcript: null }),
    )

    expect(await screen.findByText(t('analysis.disabledTitle'))).toBeInTheDocument()
    // No invitation, no button, and not even the call's own facts — there is
    // nothing here to be curious about.
    expect(runButton()).toBeNull()
    expect(retryButton()).toBeNull()
    expect(screen.queryByText(t('analysis.notAnalysedTitle'))).toBeNull()
    expect(screen.queryByText('Aziz Karimov')).toBeNull()
  })
})

describe('row 2 — the flag is off but rows exist', () => {
  /**
   * The row that proves the table is read IN ORDER. This response also
   * satisfies row 7, and a reader who takes the table as an unordered set
   * lands there and renders a control that answers 409.
   */
  it('shows the score read-only, with no button anywhere', async () => {
    showing(makeCallAnalysis({ enabled: false }))

    expect(await screen.findByText(t('analysis.readOnlyNote'))).toBeInTheDocument()
    // The rows ARE shown — the work was paid for.
    expect(screen.getByText(t('analysis.sectionScore'))).toBeInTheDocument()
    expect(screen.getByText('78')).toBeInTheDocument()
    expect(runButton()).toBeNull()
    expect(retryButton()).toBeNull()
  })

  it('offers no retry on a failed call while the flag is off', async () => {
    showing(
      makeCallAnalysis({
        enabled: false,
        state: makeState({
          stage: 'failed',
          failure_code: 'provider_network',
          failure_stage: 'transcribe',
          failure_detail: 'connection reset',
        }),
        score: null,
        transcript: null,
      }),
    )

    expect(await screen.findByText(t('analysis.failure.provider_network'))).toBeInTheDocument()
    expect(retryButton()).toBeNull()
  })
})

describe('row 3 — no state row', () => {
  it('invites the reader to queue it, and says which call it is', async () => {
    showing(makeCallAnalysis({ state: null, score: null, transcript: null }))

    expect(await screen.findByText(t('analysis.notAnalysedTitle'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.notAnalysedHint'))).toBeInTheDocument()
    // The call's own facts, so nobody has to leave the page to know whose
    // conversation this is (§7.4).
    expect(screen.getByText('Aziz Karimov')).toBeInTheDocument()
    expect(screen.getByText('+998 90 111 22 33')).toBeInTheDocument()
    expect(runButton()).toBeInTheDocument()
  })

  it('posts the call id and never asks for a re-score', async () => {
    const posts: string[] = []
    const bodies: string[] = []
    respond((url, init) => {
      if (init?.method === 'POST') {
        posts.push(url)
        bodies.push(String(init.body))
        return jsonResponse(200, makeState({ stage: 'queued' }))
      }
      return jsonResponse(
        200,
        makeCallAnalysis({ state: null, score: null, transcript: null }),
      )
    })

    renderPage()
    const button = await screen.findByRole('button', { name: t('analysis.runButton') })
    await userEvent.click(button)

    await waitFor(() => expect(bodies.length).toBe(1))
    expect(posts[0]).toContain(`/api/v1/analysis/calls/${CALL_ID}`)
    // `force: true` clears the transcript and the score so both are recomputed
    // — the only way to spend money twice on one call. The panel never sends
    // it (§6.2).
    expect(bodies[0]).toContain('"force":false')
    expect(bodies[0]).not.toContain('"force":true')
  })

  it('renders a 409 from the server as its Uzbek sentence', async () => {
    respond((_url, init) =>
      init?.method === 'POST'
        ? jsonResponse(409, {
            error: {
              code: 'analysis_cost_cap_reached',
              message: 'cap reached',
              request_id: '01J9',
            },
          })
        : jsonResponse(200, makeCallAnalysis({ state: null, score: null, transcript: null })),
    )

    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: t('analysis.runButton') }))

    expect(
      await screen.findByText(t('errors.analysis_cost_cap_reached')),
    ).toBeInTheDocument()
    expect(screen.queryByText('analysis_cost_cap_reached')).toBeNull()
  })
})

describe('rows 4 and 5 — running, and skipped', () => {
  it('names the stage while the pipeline still has work to do', async () => {
    showing(
      makeCallAnalysis({
        state: makeState({ stage: 'transcribing', scored_at: null }),
        score: null,
        transcript: null,
      }),
    )

    expect(await screen.findByText(t('analysis.stage.transcribing'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.runningHint'))).toBeInTheDocument()
    expect(runButton()).toBeNull()
    expect(retryButton()).toBeNull()
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * `skipped` is NOT a failure and must not grow a retry button.
   *
   * The call failed the §2.6 gate — no recording — and asking again cannot
   * change that. The button would answer 409 `call_not_analysable` every press,
   * and the styling must not say "something broke" about a system working
   * exactly as designed.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('explains a skipped call in one sentence, with nothing to press', async () => {
    showing(
      makeCallAnalysis({
        state: makeState({ stage: 'skipped', failure_code: 'no_audio', scored_at: null }),
        score: null,
        transcript: null,
      }),
    )

    expect(await screen.findByText(t('analysis.failure.no_audio'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.skippedHint'))).toBeInTheDocument()
    expect(runButton()).toBeNull()
    expect(retryButton()).toBeNull()
    // Not painted as a failure.
    expect(screen.queryByText(t('analysis.failedTitle'))).toBeNull()
  })
})

describe('row 6 — failed', () => {
  it('gives the Uzbek headline, the retry, and the raw detail beside it', async () => {
    showing(
      makeCallAnalysis({
        state: makeState({
          stage: 'failed',
          attempts: 3,
          failure_code: 'provider_rate_limit',
          failure_stage: 'transcribe',
          failure_detail: 'HTTP 429: quota exceeded for project',
          scored_at: null,
        }),
        score: null,
        transcript: null,
      }),
    )

    expect(await screen.findByText(t('analysis.failure.provider_rate_limit'))).toBeInTheDocument()
    expect(retryButton()).toBeInTheDocument()
    // Which half spent money before stopping.
    expect(
      screen.getByText(t('analysis.failedHalf', { half: t('analysis.half.transcribe') })),
    ).toBeInTheDocument()
    // The provider's own message: technical English BESIDE the Uzbek headline,
    // never instead of it.
    expect(screen.getByText('HTTP 429: quota exceeded for project')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })
})

describe('row 7 — completed', () => {
  it('renders the score block and the transcript block', async () => {
    showing(makeCallAnalysis())

    expect(await screen.findByText(t('analysis.sectionScore'))).toBeInTheDocument()
    expect(screen.getByText('78')).toBeInTheDocument()
    expect(screen.getByText(t('analysis.band.good'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.pointsOf', { earned: 78, max: 100 }))).toBeInTheDocument()

    // All four blocks were assessed, so all four bars are drawn.
    expect(screen.getByText(t('analysis.block.script'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.block.sales_skill'))).toBeInTheDocument()

    expect(screen.getByText(t('analysis.sectionTranscript'))).toBeInTheDocument()
    expect(screen.getByText('Assalomu alaykum, Bonvi kompaniyasidan.')).toBeInTheDocument()
    // The timestamps are rendered because phase 2's click-to-seek reads them;
    // they are not controls today.
    expect(screen.getByText('[00:00]')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '[00:00]' })).toBeNull()
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * The two rules the port found the hard way, on screen.
   *
   * `sales_skill` was entirely "does not apply" — a returning customer
   * reordering what they always order. It is absent from `blocks` and present
   * in `block_details.blocks` with `score: 0`. Drawing it would tell a manager
   * the employee lost a quarter of the call; a header of "60 / 100" would say
   * the same thing more quietly.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('draws no bar for a block nobody was assessed on, and says 60 / 75', async () => {
    showing(makeCallAnalysis({ score: makeScoreWithNaBlock() }))

    expect(await screen.findByText(t('analysis.sectionScore'))).toBeInTheDocument()

    expect(screen.getByText(t('analysis.block.script'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.block.communication'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.block.resolution'))).toBeInTheDocument()
    // The one that was never assessed.
    expect(screen.queryByText(t('analysis.block.sales_skill'))).toBeNull()

    // Honest, out of the maxima that actually applied.
    expect(screen.getByText(t('analysis.pointsOf', { earned: 60, max: 75 }))).toBeInTheDocument()
    expect(screen.queryByText(t('analysis.pointsOf', { earned: 60, max: 100 }))).toBeNull()
    expect(screen.getByText(t('analysis.naNote', { count: 3 }))).toBeInTheDocument()

    // And no 0-width bar left behind: every bar drawn has a non-zero value.
    for (const bar of screen.getAllByRole('progressbar')) {
      expect(Number(bar.getAttribute('aria-valuenow'))).toBeGreaterThan(0)
    }
  })

  it('renders the review reasons as sentences when a score needs a person', async () => {
    showing(
      makeCallAnalysis({
        score: {
          ...makeCallAnalysis().score!,
          needs_review: true,
          confidence_pct: 61,
          review_reasons: [
            { code: 'low_confidence', params: { confidence_pct: 61, threshold: 70 } },
            { code: 'red_flag', params: { types: ['shouting'] } },
          ],
        },
      }),
    )

    expect(await screen.findByText(t('analysis.reviewBadge'))).toBeInTheDocument()
    expect(
      screen.getByText(
        t('analysis.review.low_confidence', { confidence_pct: 61, threshold: 70 }),
      ),
    ).toBeInTheDocument()
    // The stored value is a machine code; the sentence names the breach.
    expect(screen.queryByText(/low_confidence/)).toBeNull()
  })

  it('shows a red flag with its evidence, and marks a repeat as uncharged', async () => {
    showing(
      makeCallAnalysis({
        score: {
          ...makeCallAnalysis().score!,
          red_flags: [
            {
              type: 'shouting',
              label: 'Baqirdi',
              severity: 'high',
              timestamp: '[01:12]',
              quote: 'Nega tushunmayapsiz!',
              penalty: -20,
              counted: true,
            },
            {
              type: 'shouting',
              label: 'Baqirdi',
              severity: 'high',
              timestamp: '[02:40]',
              quote: 'Yana aytaman!',
              penalty: -20,
              counted: false,
            },
          ],
        },
      }),
    )

    expect(await screen.findAllByText(t('analysis.redFlag.shouting'))).toHaveLength(2)
    expect(screen.getByText('Nega tushunmayapsiz!')).toBeInTheDocument()
    // The penalty is charged once per type; saying so stops a manager adding
    // the numbers up and getting a different total.
    expect(screen.getByText(t('analysis.flagPenalty', { penalty: -20 }))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.flagRepeat'))).toBeInTheDocument()
  })
})

describe('the permission split of §6.1', () => {
  it('shows a manager the analysis and not the button', async () => {
    // `manager` holds `analysis:read` and not `analysis:run`: reviewing work is
    // free, running it spends money.
    signIn([Perm.ANALYSIS_READ])
    showing(makeCallAnalysis({ state: null, score: null, transcript: null }))

    expect(await screen.findByText(t('analysis.notAnalysedTitle'))).toBeInTheDocument()
    expect(runButton()).toBeNull()
  })

  it('shows an admin both', async () => {
    signIn([Perm.ANALYSIS_READ, Perm.ANALYSIS_RUN])
    showing(makeCallAnalysis({ state: null, score: null, transcript: null }))

    expect(await screen.findByRole('button', { name: t('analysis.runButton') })).toBeInTheDocument()
  })
})

describe('the three QueryBoundary states', () => {
  it('renders the skeleton before the response arrives', async () => {
    let release: ((response: Response) => void) | undefined
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { release = resolve }))

    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
    release?.(jsonResponse(200, makeCallAnalysis()))
    await waitFor(() => expect(screen.queryByTestId('query-loading')).toBeNull())
  })

  /**
   * A call belonging to another agent answers 404, exactly as everywhere else,
   * so this page's error state is also its "not yours" state — and it says the
   * same thing for both, which is the point of the server's choice.
   */
  it('renders a 404 as the Uzbek sentence, never as the code', async () => {
    respond(() =>
      jsonResponse(404, {
        error: { code: 'not_found', message: 'Not found', request_id: '01J9' },
      }),
    )

    renderPage()

    const box = await screen.findByTestId('query-error')
    expect(within(box).getByText(t('errors.not_found'))).toBeInTheDocument()
    expect(screen.queryByText('Not found')).toBeNull()
  })
})
