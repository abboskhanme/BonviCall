/**
 * `/sales` — the queue.
 *
 * What it must not get wrong, in order of how much damage it does:
 *
 *  1. THE SUMMARY MUST NOT FOLLOW THE LIST'S FILTERS. If picking "Shubhali"
 *     also narrowed the counts, two of the three cards would drop to zero —
 *     the filter would erase its own basis and the cards would stop working
 *     as buttons. The server refuses those parameters; this test proves the
 *     panel never sends them;
 *  2. the queue opens on UNDECIDED. A decided sale must not be back at the top
 *     of the queue tomorrow, or the queue never ends;
 *  3. `not_checkable` is NOT a kind of `ok` — it is its own card with its own
 *     count, and it is never folded into "clean";
 *  4. the walk-in section asks a DIFFERENT question. Classes and rules are
 *     meaningless under a shared code, so those filters must not be offered
 *     there — they would only ever return an empty list;
 *  5. the section filter travels with the out-of-scope switch. As a third tab
 *     that dropped `client_kind`, a walk-in sale of an excluded customer
 *     appeared in no list at all (the server measured 47 of them);
 *  6. a reader without `settings:write` gets no import button — the server
 *     refuses either way, but a button that always 403s is a bug with a
 *     border.
 *
 * Plus the three `QueryBoundary` states, as CONVENTIONS-CLIENT.md §10 requires.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '@/modules/auth/store'
import { exportCompliance } from '@/modules/sales/export'
import { exportOverLimitSales } from '@/modules/sales/exportOverLimit'
import { exportSuspiciousSales } from '@/modules/sales/exportSuspicious'
import { SalesPage } from '@/modules/sales/SalesPage'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'

import {
  makeBranches,
  makeItem,
  makeList,
  makeSummary,
  makeTimeline,
  makeWalkInSummary,
} from './fixtures'

/**
 * The workbook writer is stubbed: this file is about what the PAGE asks for,
 * and the file's own layout is checked in `export.test.ts` without a browser.
 * Left real, the click would load `write-excel-file` and try to save a file
 * from jsdom.
 */
vi.mock('@/modules/sales/export', () => ({
  exportCompliance: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/modules/sales/exportSuspicious', () => ({
  exportSuspiciousSales: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/modules/sales/exportOverLimit', () => ({
  exportOverLimitSales: vi.fn().mockResolvedValue(undefined),
}))

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'tester@bonvi.uz',
      full_name: 'Test User',
      role: 'admin',
      permissions,
      must_change_password: false,
      agent_id: null,
    },
    permissions: new Set(permissions),
    loginError: null,
  })
}

/** Every URL this page touches, each answering for itself. */
function serving({
  list = makeList(),
  summary = makeSummary(),
} = {}) {
  fetchMock.mockImplementation((input) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    // The order matters: `/sales/compliance` is a prefix of the other two.
    if (url.includes('/sales/compliance/summary')) return Promise.resolve(jsonResponse(200, summary))
    if (url.includes('/sales/compliance/timeline')) {
      return Promise.resolve(jsonResponse(200, makeTimeline()))
    }
    if (url.includes('/sales/compliance')) return Promise.resolve(jsonResponse(200, list))
    if (url.includes('/sales/branches')) return Promise.resolve(jsonResponse(200, makeBranches()))
    if (url.includes('/agents')) return Promise.resolve(jsonResponse(200, { items: [], total: 0 }))
    return Promise.resolve(jsonResponse(200, {}))
  })
}

function renderPage(entry = '/sales') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <SalesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Every query string sent to the list endpoint, in order. */
function listCalls(): URLSearchParams[] {
  return fetchMock.mock.calls
    .map((call) => String(call[0]))
    .filter((url) => /\/sales\/compliance(\?|$)/.test(url))
    .map((url) => new URLSearchParams(url.split('?')[1] ?? ''))
}

function summaryCalls(): URLSearchParams[] {
  return fetchMock.mock.calls
    .map((call) => String(call[0]))
    .filter((url) => url.includes('/sales/compliance/summary'))
    .map((url) => new URLSearchParams(url.split('?')[1] ?? ''))
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  signIn([Perm.REPORTS_READ, Perm.SETTINGS_WRITE, Perm.CALLS_NOTE, Perm.CALLS_READ])
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

// ── The three QueryBoundary states ────────────────────────────

describe('the three non-success states', () => {
  it('renders a skeleton while the queue is in flight', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getAllByTestId('query-loading').length).toBeGreaterThan(0)
  })

  it('renders an error state when the queue fails', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(
        jsonResponse(500, { error: { code: 'internal_error', message: 'x', request_id: 'r' } }),
      ),
    )
    renderPage()
    expect((await screen.findAllByTestId('query-error')).length).toBeGreaterThan(0)
  })

  it('says the queue is FINISHED rather than that there is no data', async () => {
    // ⚠️ Three different empty sentences, because they call for three
    // different next actions. On the default filter an empty list means the
    // work is done — not that something failed to load.
    serving({ list: makeList([]) })
    renderPage()
    expect(await screen.findByText(t('sales.emptyQueueHint'))).toBeInTheDocument()
  })
})

// ── The summary ───────────────────────────────────────────────

describe('the three class counts', () => {
  it('keeps all three on screen, and not_checkable is its own card', async () => {
    // ⚠️ `not_checkable` is NOT a kind of `ok`. It measures SAP's own data
    // quality and folding it into "clean" would write "all is well" over the
    // one number that says our records are incomplete.
    serving()
    renderPage()
    expect(await screen.findByText('372')).toBeInTheDocument()
    expect(screen.getByText('45')).toBeInTheDocument()
    expect(screen.getByText('34')).toBeInTheDocument()
    // Scoped to the CARD: the same words are also an option in the verdict
    // filter below, and the card is the one that must never disappear.
    const card = screen.getByRole('button', {
      name: new RegExp(`34\\s*${t('sales.verdict.not_checkable')}`),
    })
    expect(card).toBeInTheDocument()
    expect(card).toHaveAttribute('aria-pressed', 'false')
  })

  it('NEVER sends verdict, rule or review to the summary', async () => {
    // ⚠️ THE TEST THIS FILE EXISTS FOR. With those filters applied, choosing
    // "Shubhali" would drop the other two cards to zero — the filter erasing
    // its own basis.
    serving()
    renderPage('/sales?verdict=suspicious&rule=R1&review=all&over_limit=1')
    await screen.findByText('372')

    for (const params of summaryCalls()) {
      expect(params.get('verdict')).toBeNull()
      expect(params.get('rule')).toBeNull()
      expect(params.get('review')).toBeNull()
      expect(params.get('over_limit')).toBeNull()
    }
    expect(summaryCalls().length).toBeGreaterThan(0)
  })

  it('carries the scope filters TO the summary, so both halves agree', async () => {
    serving()
    renderPage('/sales?date_from=2026-08-01&search=К02711')
    await screen.findByText('372')
    const params = summaryCalls().at(-1)
    expect(params?.get('date_from')).toBe('2026-08-01')
    expect(params?.get('search')).toBe('К02711')
  })

  it('filters the list when a card is pressed', async () => {
    serving()
    renderPage()
    await screen.findByText('372')
    await userEvent.click(screen.getByRole('button', { name: /45/ }))
    await waitFor(() => {
      expect(listCalls().at(-1)?.get('verdict')).toBe('suspicious')
    })
  })
})

// ── The queue's default ───────────────────────────────────────

describe('the review filter', () => {
  it('opens on UNDECIDED', async () => {
    // A sale that has been looked at must not be back at the top of the queue
    // tomorrow, or the queue never ends.
    serving()
    renderPage()
    await screen.findByText('372')
    expect(listCalls().at(-1)?.get('review')).toBe('new')
  })

  it('sends an explicit `all` rather than dropping the parameter', async () => {
    // ⚠️ The server's default is `new`. An omitted parameter would serve the
    // queue while the picker read "Hammasi".
    serving()
    renderPage()
    await screen.findByText('372')
    await userEvent.selectOptions(
      screen.getByLabelText(t('sales.col.decision')),
      'all',
    )
    await waitFor(() => expect(listCalls().at(-1)?.get('review')).toBe('all'))
  })
})

// ── The sections ──────────────────────────────────────────────

describe('the two sections and the out-of-scope switch', () => {
  it('asks a different question among walk-ins — the ticket limit, not the classes', async () => {
    serving({ summary: makeWalkInSummary() })
    renderPage('/sales?client_kind=walk_in')
    expect(await screen.findByText('718')).toBeInTheDocument()
    expect(screen.getByText('23')).toBeInTheDocument()
    // The class and rule pickers are meaningless here: every sale is
    // `not_checkable`, so they would only ever return an empty list.
    expect(screen.queryByLabelText(t('sales.col.verdict'))).toBeNull()
    expect(screen.queryByLabelText(t('sales.filter.rule'))).toBeNull()
  })

  it('keeps the section filter when the out-of-scope switch is on', async () => {
    // ⚠️ As a third TAB this dropped `client_kind`, and a walk-in sale of an
    // excluded customer then appeared in no section at all.
    serving({ summary: makeWalkInSummary() })
    renderPage('/sales?client_kind=walk_in')
    await screen.findByText('718')
    await userEvent.click(screen.getByRole('button', { name: t('sales.kind.excluded') }))

    await waitFor(() => {
      const params = listCalls().at(-1)
      expect(params?.get('out_of_scope')).toBe('true')
      expect(params?.get('client_kind')).toBe('walk_in')
    })
  })

  it('drops the class filters when the section changes', async () => {
    // They belonged to the other set; left in place they land the reader on an
    // empty page they read as a fault.
    serving()
    renderPage('/sales?verdict=suspicious')
    await screen.findByText('372')
    await userEvent.click(screen.getByRole('tab', { name: t('sales.kind.walk_in') }))
    await waitFor(() => {
      expect(listCalls().at(-1)?.get('verdict')).toBeNull()
    })
  })
})

// ── The row ───────────────────────────────────────────────────

describe('a queue row', () => {
  it('carries the operation number, because the evidence is checked in SAP', async () => {
    serving()
    renderPage()
    expect(await screen.findByText('№ 88681')).toBeInTheDocument()
  })

  it('links the last conversation to the recording', async () => {
    // ⚠️ NEW HERE. The source printed a date and a name with nothing behind
    // them, so proving the row meant finding the call by hand.
    serving()
    renderPage()
    const link = await screen.findByRole('link', { name: /12\/08\/2026|03\/08\/2026/ })
    expect(link).toHaveAttribute('href', '/calls/33333333-3333-4333-8333-333333333333')
  })

  it('writes "no conversation" out rather than leaving the cell blank', async () => {
    // A blank cell reads as "failed to load", which is the opposite
    // conclusion from "we never spoke to them".
    serving({ list: makeList([makeItem({ last_call_at: null, last_call_id: null })]) })
    renderPage()
    expect(await screen.findByText(t('sales.noCallPlain'))).toBeInTheDocument()
  })

  it('shows the customer CODE as the heading when there is no name', async () => {
    // An em dash gives nothing; a code still finds the row in SAP.
    serving({ list: makeList([makeItem({ partner_name: null })]) })
    renderPage()
    expect((await screen.findAllByText('К02711')).length).toBeGreaterThan(0)
  })

  it('shows the document currency only when it differs from dollars', async () => {
    serving({ list: makeList([makeItem({ currency: 'USD', amount: 340 })]) })
    renderPage()
    await screen.findByText('№ 88681')
    expect(screen.queryByText(/340 USD/)).toBeNull()
  })
})

// ── Paging ────────────────────────────────────────────────────

describe('cursor paging', () => {
  it('asks for a total only on the FIRST page', async () => {
    // A count over this aggregate is affordable once per filter change, not
    // once per page.
    serving({ list: makeList([makeItem()], { has_more: true, next_cursor: 'cur-2' }) })
    renderPage()
    await screen.findByText('№ 88681')
    expect(listCalls().at(-1)?.get('with_total')).toBe('true')

    await userEvent.click(screen.getByRole('button', { name: new RegExp(t('sales.nextPage')) }))
    await waitFor(() => {
      const params = listCalls().at(-1)
      expect(params?.get('cursor')).toBe('cur-2')
      expect(params?.get('with_total')).toBe('false')
    })
  })

  it('drops the cursor when a filter changes', async () => {
    // Otherwise somebody on page five who narrows a filter is served an empty
    // table and reads it as "no data".
    serving({ list: makeList([makeItem()], { has_more: true, next_cursor: 'cur-2' }) })
    renderPage()
    await screen.findByText('№ 88681')
    await userEvent.click(screen.getByRole('button', { name: new RegExp(t('sales.nextPage')) }))
    await waitFor(() => expect(listCalls().at(-1)?.get('cursor')).toBe('cur-2'))

    await userEvent.selectOptions(screen.getByLabelText(t('sales.col.decision')), 'all')
    await waitFor(() => {
      const params = listCalls().at(-1)
      expect(params?.get('cursor')).toBeNull()
      expect(params?.get('review')).toBe('all')
    })
  })

  it('sends no `sort`, because the cursor cannot express one', async () => {
    // ⚠️ Three of the source's four sort orders were deliberately not ported:
    // a sort a keyset cursor cannot express silently loses rows.
    serving()
    renderPage()
    await screen.findByText('№ 88681')
    expect(listCalls().at(-1)?.get('sort')).toBeNull()
    expect(listCalls().at(-1)?.get('order')).toBe('desc')
  })
})

// ── Access ────────────────────────────────────────────────────

describe('permissions', () => {
  it('offers no import or digest button without settings:write', async () => {
    signIn([Perm.REPORTS_READ])
    serving()
    renderPage()
    await screen.findByText('№ 88681')
    expect(screen.queryByRole('button', { name: t('sales.import.button') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('sales.digest.button') })).toBeNull()
  })

  it('shows the last conversation as plain text when calls cannot be opened', async () => {
    signIn([Perm.REPORTS_READ])
    serving()
    renderPage()
    await screen.findByText('№ 88681')
    expect(screen.queryByRole('link', { name: /2026/ })).toBeNull()
  })

  it('offers no decision button in the card without calls:note', async () => {
    signIn([Perm.REPORTS_READ])
    serving()
    renderPage()
    await userEvent.click(await screen.findByText('№ 88681'))
    expect(await screen.findByText(t('sales.card.facts'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('sales.card.decide') })).toBeNull()
  })
})

// ── The card ──────────────────────────────────────────────────

describe('the sale card', () => {
  it('opens on the row and carries the facts and the sentence', async () => {
    serving()
    renderPage()
    await userEvent.click(await screen.findByText('№ 88681'))

    expect(await screen.findByText(t('sales.card.facts'))).toBeInTheDocument()
    // The "why", built from the evidence rather than invented.
    expect(
      screen.getByText(t('sales.why.noCallBefore', { count: 9, date: '03/08/2026' })),
    ).toBeInTheDocument()
    expect(screen.getByText('RN-004512')).toBeInTheDocument()
  })

  it('asks the chain for THIS customer, unfiltered and not only-suspicious', async () => {
    // ⚠️ `only_suspicious` defaults to TRUE on the server: without overriding
    // it a clean customer would come back with no chain at all. The page's own
    // employee and branch filters are deliberately not passed on — they would
    // cut the very conversations that explain the verdict.
    serving()
    renderPage('/sales?agent_id=22222222-2222-4222-8222-222222222222')
    await userEvent.click(await screen.findByText('№ 88681'))
    await screen.findByText(t('sales.card.facts'))

    await waitFor(() => {
      const url = fetchMock.mock.calls
        .map((call) => String(call[0]))
        .find((candidate) => candidate.includes('/sales/compliance/timeline'))
      expect(url).toBeDefined()
      const params = new URLSearchParams(url?.split('?')[1] ?? '')
      expect(params.get('only_suspicious')).toBe('false')
      expect(params.get('search')).toBe('К02711')
      expect(params.get('agent_id')).toBeNull()
      // ±30 days around the sale, not the page's window.
      expect(params.get('date_from')).toBe('2026-07-13')
      expect(params.get('date_to')).toBe('2026-09-11')
    })
  })

  it('renders the chain in the SERVER order and does not re-sort it', async () => {
    // ⚠️ On one day the call precedes the sale, and that rule lives on the
    // server — where the verdict is computed with it. Re-sorting by `at` would
    // put the sale first and contradict it.
    serving()
    renderPage()
    await userEvent.click(await screen.findByText('№ 88681'))
    const chain = await screen.findByRole('list')
    const rows = within(chain).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    const text = rows.map((row) => row.textContent ?? '')
    // The earlier sale, then the call, then THIS sale — on 12.08 the call
    // comes first, exactly as the server ordered it.
    expect(text[0]).toContain('88010')
    expect(text[1]).toContain(t('sales.card.call'))
    expect(text[2]).toContain(t('sales.card.thisSale'))
  })

  it('explains itself instead of drawing an empty chain for a shared code', async () => {
    // ⚠️ Zeroes here would be an accusation: the point is not that nobody
    // called, it is that the customer cannot be identified at all.
    serving({
      list: makeList([
        makeItem({
          phone_key: null,
          phone: null,
          verdict: 'not_checkable',
          broken_rules: [],
          skip_reason: 'generic_code',
        }),
      ]),
    })
    renderPage()
    await userEvent.click(await screen.findByText('№ 88681'))
    expect(await screen.findByText(t('sales.card.noPhone'))).toBeInTheDocument()
    expect(screen.getByText(t('sales.skip.generic_code'))).toBeInTheDocument()
    expect(screen.queryByText(t('sales.card.timeline'))).toBeNull()
  })

  it('offers "put back" for a customer already out of scope', async () => {
    // ⚠️ Without `partner_excluded` on the row the card would open saying
    // "Exclude" for a customer already excluded, and there would be no way
    // back from this screen.
    serving({ list: makeList([makeItem({ partner_excluded: true })]) })
    renderPage()
    await userEvent.click(await screen.findByText('№ 88681'))
    expect(
      await screen.findByRole('button', { name: t('sales.exclusion.include') }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('sales.exclusion.action') })).toBeNull()
  })
})

describe('the export button', () => {
  it('asks for the WHOLE selection, from its first row', async () => {
    // ⚠️ The table shows 50 rows and the file must hold every row the filter
    // holds. A file built from the page on screen would state "12 suspicious
    // sales" for a filter holding 451 — and it is read by somebody who never
    // saw the screen.
    serving()
    renderPage('/sales?cursor=page-five')
    await screen.findByText('№ 88681')

    await userEvent.click(screen.getByRole('button', { name: t('sales.export.button') }))

    await waitFor(() => expect(exportCompliance).toHaveBeenCalled())
    const walk = listCalls().at(-1)
    // The largest page the server will serve, from the beginning — never the
    // cursor the reader happens to be standing on.
    expect(walk?.get('limit')).toBe('200')
    expect(walk?.get('cursor')).toBeNull()
  })

  it('writes the coverage into the file, so an emailed sheet keeps its context', async () => {
    serving()
    renderPage('/sales?search=%D0%9A02711&date_from=2026-07-22&date_to=2026-08-20')
    await screen.findByText('№ 88681')

    await userEvent.click(screen.getByRole('button', { name: t('sales.export.button') }))

    await waitFor(() => expect(exportCompliance).toHaveBeenCalled())
    const options = vi.mocked(exportCompliance).mock.calls.at(-1)?.[0]
    expect(options?.since).toBe('2026-07-22')
    expect(options?.until).toBe('2026-08-20')
    expect(options?.scope).toContain(t('sales.kind.regular'))
    expect(options?.scope).toContain('К02711')
    // The queue's own default is part of what the file covers, not a detail
    // to leave out: a file of undecided sales is not a file of all of them.
    expect(options?.scope).toContain(t('sales.review.new'))
    expect(options?.rows).toHaveLength(1)
  })

  it('stays disabled until there is something to write', async () => {
    serving({ list: makeList([], { total: 0 }) })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: t('sales.export.button') })).toBeDisabled(),
    )
  })
})

describe('the section report', () => {
  /** Every query string sent to the chain endpoint. */
  function timelineCalls(): URLSearchParams[] {
    return fetchMock.mock.calls
      .map((call) => String(call[0]))
      .filter((url) => url.includes('/sales/compliance/timeline'))
      .map((url) => new URLSearchParams(url.split('?')[1] ?? ''))
  }

  it('takes the decided sales too, not just the queue', async () => {
    // ⚠️ The list defaults to "undecided". Left that way, a file called
    // "suspicious sales" would quietly hide the justified ones and its
    // decision sheet would read 100 % "Ko'rilmagan" — a fact about the query
    // that reads as a fact about the work.
    serving()
    renderPage()
    await screen.findByText('№ 88681')

    await userEvent.click(
      screen.getByRole('button', { name: t('sales.exportSuspicious.button') }),
    )

    await waitFor(() => expect(exportSuspiciousSales).toHaveBeenCalled())
    const walk = listCalls().at(-1)
    expect(walk?.get('verdict')).toBe('suspicious')
    expect(walk?.get('review')).toBe('all')
  })

  it('asks the chain for the CLEAN customers as well', async () => {
    // Without them the "customers" column can only repeat the suspicious
    // count, which is the column answering a question it was not asked.
    serving()
    renderPage()
    await screen.findByText('№ 88681')

    await userEvent.click(
      screen.getByRole('button', { name: t('sales.exportSuspicious.button') }),
    )

    await waitFor(() => expect(exportSuspiciousSales).toHaveBeenCalled())
    const chain = timelineCalls().at(-1)
    expect(chain?.get('only_suspicious')).toBe('false')
    expect(chain?.get('max_clients')).toBe('1000')
  })

  it('still writes the file when the chain request fails', async () => {
    // The figures matter more than the sequence: the file comes out with five
    // sheets instead of six rather than not at all.
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/sales/compliance/summary')) {
        return Promise.resolve(jsonResponse(200, makeSummary()))
      }
      if (url.includes('/sales/compliance/timeline')) return Promise.reject(new Error('down'))
      if (url.includes('/sales/compliance')) return Promise.resolve(jsonResponse(200, makeList()))
      if (url.includes('/sales/branches')) {
        return Promise.resolve(jsonResponse(200, makeBranches()))
      }
      return Promise.resolve(jsonResponse(200, { items: [], total: 0 }))
    })
    renderPage()
    await screen.findByText('№ 88681')

    await userEvent.click(
      screen.getByRole('button', { name: t('sales.exportSuspicious.button') }),
    )

    await waitFor(() => expect(exportSuspiciousSales).toHaveBeenCalled())
    expect(vi.mocked(exportSuspiciousSales).mock.calls.at(-1)?.[0].timeline).toBeUndefined()
    expect(screen.queryByText(t('sales.export.failed'))).toBeNull()
  })

  it('writes the over-limit file in the walk-in section, with the limit it used', async () => {
    serving({ summary: makeWalkInSummary() })
    renderPage('/sales?client_kind=walk_in')
    await screen.findByText('№ 88681')

    await userEvent.click(
      screen.getByRole('button', { name: t('sales.exportOverLimit.button') }),
    )

    await waitFor(() => expect(exportOverLimitSales).toHaveBeenCalled())
    const walk = listCalls().at(-1)
    expect(walk?.get('over_limit')).toBe('true')
    expect(walk?.get('review')).toBe('all')
    const options = vi.mocked(exportOverLimitSales).mock.calls.at(-1)?.[0]
    // The threshold is stated in the file, so an old report says which basis
    // produced it after somebody changes the setting.
    expect(options?.limit).toBe(makeWalkInSummary().walk_in_limit)
  })

  it('offers no section report out of scope', async () => {
    // Those sales are precisely the ones NOT being checked, so "the suspicious
    // ones among them" is not a question this product asks.
    serving()
    renderPage('/sales?out_of_scope=1')
    await screen.findByText('№ 88681')

    expect(screen.queryByRole('button', { name: t('sales.exportSuspicious.button') })).toBeNull()
    expect(screen.queryByRole('button', { name: t('sales.exportOverLimit.button') })).toBeNull()
  })
})

describe('the chain reads the direction this product actually sends', () => {
  it('shows an unanswered INCOMING call as ours that went unanswered', async () => {
    /* ⚠️ A live bug until 2026-09-18: the card compared against `inbound`,
       which is BonviZvonki's word — `core/enums.py::CallDirection` sends
       `incoming`/`outgoing`. The comparison was always false, so every call
       was drawn as outgoing and an unanswered incoming call said "the customer
       did not pick up" when it was ours. */
    const timeline = makeTimeline()
    const client = timeline.clients?.[0]
    if (!client) throw new Error('the fixture has no customer')
    serving({})
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/sales/compliance/summary')) {
        return Promise.resolve(jsonResponse(200, makeSummary()))
      }
      if (url.includes('/sales/compliance/timeline')) {
        return Promise.resolve(
          jsonResponse(200, {
            ...timeline,
            clients: [
              {
                ...client,
                events: (client.events ?? []).map((event) =>
                  event.kind === 'call'
                    ? { ...event, direction: 'incoming', answered: false }
                    : event,
                ),
              },
            ],
          }),
        )
      }
      if (url.includes('/sales/compliance')) return Promise.resolve(jsonResponse(200, makeList()))
      if (url.includes('/sales/branches')) {
        return Promise.resolve(jsonResponse(200, makeBranches()))
      }
      return Promise.resolve(jsonResponse(200, { items: [], total: 0 }))
    })

    renderPage()
    await userEvent.click(await screen.findByText('№ 88681'))
    const chain = await screen.findByRole('list')

    expect(within(chain).getByText(new RegExp(t('sales.card.dirInbound')))).toBeInTheDocument()
    expect(within(chain).getByText(new RegExp(t('sales.card.noAnswer')))).toBeInTheDocument()
  })
})
