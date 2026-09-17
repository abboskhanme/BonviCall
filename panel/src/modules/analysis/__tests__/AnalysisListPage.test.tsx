/**
 * `/analysis` — the list, pinned where it can break silently
 * (CONVENTIONS-CLIENT.md §10: "a page test asserts all three QueryBoundary
 * states render").
 *
 * What is asserted here and why each is worth a test:
 *
 *  1. rows render from a mocked response, with the score, the band and the
 *     stage the row actually carries;
 *  2. a row that is not scored yet shows a dash rather than a 0 — "queued" and
 *     "scored zero" are opposite statements about an employee;
 *  3. loading, and an error `code` from the §9 envelope becoming the Uzbek
 *     sentence rather than the code;
 *  4. the empty state distinguishes "nothing has been analysed yet" — the state
 *     this deployment is actually in, with `analysis.enabled` seeded false —
 *     from "nothing matches this filter";
 *  5. the next page is requested with `cursor=` and never with an offset;
 *  6. the URL is the screen state: filters read out of it, and sent under the
 *     SERVER's own parameter names, repeated rather than comma-joined.
 *
 * `fetch` is mocked rather than the api module, so `client.ts` parses the
 * envelope for real and the assertions cover the wire.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalysisListPage } from '@/modules/analysis/AnalysisListPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

import { AGENT_ID, makeCallHeader, makeListItem, makeListPage } from './fixtures'

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

function renderPage(initialPath = '/analysis') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[initialPath]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/analysis" element={<AnalysisListPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Every `/analysis/calls` request the page made, in order. */
function listRequests(): string[] {
  return fetchMock.mock.calls
    .map(([input]) =>
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url,
    )
    .filter((url) => url.includes('/api/v1/analysis/calls'))
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.ANALYSIS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('the scored-call list', () => {
  it('renders a row per analysed call', async () => {
    respond(() =>
      jsonResponse(
        200,
        makeListPage([
          makeListItem(),
          makeListItem({
            call: makeCallHeader({
              call_id: 'second',
              agent_name: 'Nodira Yusupova',
              remote_number: '901234567',
            }),
            overall_score: 42,
            needs_review: true,
            red_flag_types: ['shouting'],
          }),
        ]),
      ),
    )

    renderPage()

    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(3) // header + two
    // Both numbers in the readable local form, not as they arrived.
    expect(within(table).getByText('+998 90 111 22 33')).toBeInTheDocument()
    expect(within(table).getByText('90 123 45 67')).toBeInTheDocument()
    expect(within(table).getByText('78')).toBeInTheDocument()
    expect(within(table).getByText('42')).toBeInTheDocument()
    // The band is the server's own vocabulary, coloured from one threshold set.
    expect(within(table).getByText(t('analysis.band.good'))).toBeInTheDocument()
    expect(within(table).getByText(t('analysis.band.poor'))).toBeInTheDocument()
    // A breach names itself; it never reaches the screen as `shouting`.
    expect(within(table).getByText(t('analysis.redFlag.shouting'))).toBeInTheDocument()
    expect(within(table).getByText(t('analysis.reviewBadge'))).toBeInTheDocument()
  })

  /**
   * "Not scored yet" and "scored zero" are opposite statements about an
   * employee, and `overall_score` is null for every row that has not reached
   * `completed`. A 0 in this column would be an accusation.
   */
  it('shows a dash rather than a zero for a call that is not scored yet', async () => {
    respond(() =>
      jsonResponse(
        200,
        makeListPage([makeListItem({ stage: 'queued', overall_score: null, scored_at: null })]),
      ),
    )

    renderPage()

    const table = await screen.findByRole('table')
    const [header, row] = within(table).getAllByRole('row')
    const columns = within(header as HTMLElement)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent)
    const scoreColumn = columns.indexOf(t('analysis.colScore'))
    expect(scoreColumn).toBeGreaterThan(-1)

    // Asserted by COLUMN rather than by "a dash is somewhere in the row": the
    // flags cell carries one too, and this is the cell that must not hold a 0.
    const cell = within(row as HTMLElement).getAllByRole('cell')[scoreColumn]
    expect(cell).toHaveTextContent('—')
    expect(cell).not.toHaveTextContent('0')
    expect(within(table).getByText(t('analysis.stage.queued'))).toBeInTheDocument()
  })

  it('says WHY a call was skipped in the same cell as the stage', async () => {
    respond(() =>
      jsonResponse(
        200,
        makeListPage([
          makeListItem({ stage: 'skipped', failure_code: 'no_audio', overall_score: null }),
        ]),
      ),
    )

    renderPage()

    const table = await screen.findByRole('table')
    expect(within(table).getByText(t('analysis.stage.skipped'))).toBeInTheDocument()
    expect(within(table).getByText(t('analysis.failure.no_audio'))).toBeInTheDocument()
  })

  it('renders the loading state before the response arrives', async () => {
    let release: ((response: Response) => void) | undefined
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { release = resolve }))

    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
    release?.(jsonResponse(200, makeListPage([makeListItem()])))
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
   * ══════════════════════════════════════════════════════════════════════
   * The state this deployment is actually in.
   *
   * `analysis.enabled` is seeded false, so on a live system this list is
   * legitimately empty and the sentence has to say something a reader can act
   * on — with the page that reports whether the module is switched on one
   * click away. A generic "nothing here" would leave them guessing whether the
   * feature is broken.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('distinguishes "nothing analysed yet" from "nothing matches this filter"', async () => {
    respond(() => jsonResponse(200, makeListPage([])))

    const { unmount } = renderPage()
    expect(await screen.findByText(t('analysis.emptyAll'))).toBeInTheDocument()
    expect(screen.getByText(t('analysis.emptyAllHint'))).toBeInTheDocument()
    // And a way through to the answer.
    expect(screen.getAllByRole('link', { name: t('analysis.openQueue') }).length).toBeGreaterThan(0)
    unmount()

    renderPage('/analysis?stage=failed')
    expect(await screen.findByText(t('analysis.emptyFiltered'))).toBeInTheDocument()
    expect(screen.queryByText(t('analysis.emptyAll'))).toBeNull()
  })
})

describe('filters', () => {
  it('reads them out of the URL and sends the server its own names', async () => {
    respond(() => jsonResponse(200, makeListPage([makeListItem()])))

    renderPage(
      `/analysis?agent_id=${AGENT_ID}&stage=completed&score_band=good` +
        '&needs_review=true&date_from=2026-09-01&date_to=2026-09-15',
    )

    await screen.findByRole('table')
    const url = listRequests()[0] ?? ''
    // All three are `list[...]` on the server and would 422 comma-joined.
    expect(url).toContain(`agent_id=${AGENT_ID}`)
    expect(url).toContain('stage=completed')
    expect(url).toContain('score_band=good')
    expect(url).toContain('needs_review=true')
    expect(url).toContain('date_from=2026-09-01')
    expect(url).toContain('date_to=2026-09-15')
  })

  it('ignores a band or a stage the server would refuse', async () => {
    respond(() => jsonResponse(200, makeListPage([makeListItem()])))

    // A hand-edited or stale link. Forwarding it would be a 422 the reader
    // cannot act on; dropping it shows the unfiltered list, which they can.
    renderPage('/analysis?stage=nearly&score_band=superb')

    await screen.findByRole('table')
    const url = listRequests()[0] ?? ''
    expect(url).not.toContain('stage=')
    expect(url).not.toContain('score_band=')
  })

  it('clears every filter at once, leaving none behind', async () => {
    respond(() => jsonResponse(200, makeListPage([makeListItem()])))

    renderPage('/analysis?stage=failed&score_band=poor&needs_review=true&date_from=2026-09-01')
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: t('analysis.filterReset') }))

    await waitFor(() => expect(listRequests().length).toBeGreaterThan(1))
    const url = listRequests().at(-1) ?? ''
    expect(url).not.toContain('stage=')
    expect(url).not.toContain('score_band=')
    expect(url).not.toContain('needs_review=')
    expect(url).not.toContain('date_from=')
  })

  it('offers the four bands the server accepts and nothing else', async () => {
    respond(() => jsonResponse(200, makeListPage([makeListItem()])))

    renderPage()
    await screen.findByRole('table')

    const select = screen.getByLabelText(t('analysis.filterBand'))
    expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual([
      t('analysis.filterAny'),
      t('analysis.band.excellent'),
      t('analysis.band.good'),
      t('analysis.band.average'),
      t('analysis.band.poor'),
    ])
  })

  it('asks for no agent roster when the reader may not read one', async () => {
    // `analysis:read` without `agents:read`: the column and its filter both go,
    // and nothing is requested that would answer 403.
    signIn([Perm.ANALYSIS_READ])
    respond(() => jsonResponse(200, makeListPage([makeListItem()])))

    renderPage()
    await screen.findByRole('table')

    const header = screen.getAllByRole('row')[0]
    expect(header).toBeDefined()
    expect(within(header as HTMLElement).queryByText(t('analysis.colAgent'))).toBeNull()
    expect(fetchMock.mock.calls.map(([input]) => String(input)).join(' ')).not.toContain(
      '/api/v1/agents',
    )
  })
})

describe('pagination', () => {
  it('asks for the next page with a cursor and never with an offset', async () => {
    const NEXT = 'eyJrIjpbIjIwMjYtMDktMTVUMTA6MTI6MDArMDU6MDAiLCJhIl19'
    respond((url) =>
      jsonResponse(
        200,
        url.includes(`cursor=${encodeURIComponent(NEXT)}`)
          ? makeListPage([makeListItem({ call: { ...makeListItem().call, call_id: 'p2' } })], {
              total: null,
            })
          : makeListPage([makeListItem()], { next_cursor: NEXT, has_more: true, total: 2 }),
      ),
    )

    renderPage()
    await screen.findByRole('table')

    const first = listRequests()[0] ?? ''
    expect(first).toContain('limit=50')
    expect(first).not.toContain('cursor=')
    // A COUNT over a filtered table is affordable once per filter change, not
    // once per page.
    expect(first).toContain('with_total=true')

    await userEvent.click(screen.getByRole('button', { name: t('analysis.nextPage') }))

    await waitFor(() => expect(listRequests().length).toBeGreaterThan(1))
    const second = listRequests().at(-1) ?? ''
    expect(second).toContain(`cursor=${encodeURIComponent(NEXT)}`)
    expect(second).toContain('with_total=false')

    // Keyset, not offset: an OFFSET skips and repeats rows while the pipeline
    // keeps finishing calls underneath.
    for (const url of listRequests()) {
      expect(url).not.toMatch(/[?&](offset|page|skip)=/)
    }
  })

  it('disables "previous" on the first page', async () => {
    respond(() =>
      jsonResponse(200, makeListPage([makeListItem()], { has_more: true, next_cursor: 'C1' })),
    )

    renderPage()

    expect(await screen.findByRole('button', { name: t('analysis.prevPage') })).toBeDisabled()
  })
})
