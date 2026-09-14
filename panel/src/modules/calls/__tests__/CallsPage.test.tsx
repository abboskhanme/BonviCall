/**
 * The call list, pinned where it can break silently (CONVENTIONS-CLIENT.md §10:
 * "a page test asserts all three QueryBoundary states render").
 *
 * What is asserted here and why each one is worth a test:
 *
 *  1. rows render from a mocked response — the M1 acceptance criterion;
 *  2. a call with no audio shows its REASON, not a blank cell (UC-14);
 *  3. an error `code` from the §9 envelope becomes the Uzbek sentence, never
 *     the code and never an English string (SPEC §5.3, T100);
 *  4. the next page is requested with `cursor=` and with no `offset` or `page`
 *     anywhere — keyset, not offset (SPEC §4.0, UC-19). This is the one a
 *     future refactor is most likely to get wrong, because an offset "works"
 *     until rows arrive mid-pass;
 *  5. the agent column follows the permission the server resolved, not a role.
 *
 * `fetch` is mocked rather than the api module, so `client.ts` parses the
 * envelope for real and the assertions cover the wire, not a stub of it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CallsPage } from '@/modules/calls/CallsPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

type Call = components['schemas']['CallResponse']
type AudioMissingReason = components['schemas']['AudioMissingReason']
type CallPage = components['schemas']['CallListResponse']

const AGENT_ID = '11111111-1111-4111-8111-111111111111'

/** A complete `CallResponse`, so a field the server adds breaks this file
 *  rather than being quietly absent from the fixtures. */
function makeCall(overrides: Partial<Call> = {}): Call {
  return {
    id: '22222222-2222-4222-8222-222222222222',
    seq: 1,
    agent_id: AGENT_ID,
    number_id: '33333333-3333-4333-8333-333333333333',
    installation_id: '44444444-4444-4444-8444-444444444444',
    direction: 'incoming',
    disposition: 'answered',
    call_type: 'external',
    remote_number: '+998901112233',
    remote_number_key: '901112233',
    contact_name: null,
    started_at: '2026-09-05T14:03:11+05:00',
    answered_at: '2026-09-05T14:03:20+05:00',
    ended_at: '2026-09-05T14:05:20+05:00',
    duration_sec: 120,
    ring_sec: 9,
    received_at: '2026-09-05T14:05:30+05:00',
    clock_skew_sec: 2,
    device_timezone: 'Asia/Tashkent',
    source: 'live_capture',
    reconciled_with_call_log: true,
    has_audio: true,
    audio_missing_reason: null,
    audio_duration_mismatch: false,
    agent_name: 'Aziz Karimov',
    number_e164: '+998901110000',
    device_model: 'Xiaomi Redmi Note 12',
    audio: { available: true, duration_mismatch: false },
    note: null,
    app_version: '1.4.0',
    app_variant: 'legacy28',
    ...overrides,
  }
}

/** A call whose recording never existed — a capture failure, what the gap
 *  report counts. */
function callWithoutAudio(reason: AudioMissingReason, overrides: Partial<Call> = {}): Call {
  return makeCall({
    has_audio: false,
    audio_missing_reason: reason,
    audio: { available: false, duration_mismatch: false, audio_missing_reason: reason },
    ...overrides,
  })
}

/** A call whose recording DID exist and was removed by retention — the system
 *  working correctly, and not a capture failure. */
function callWithExpiredAudio(overrides: Partial<Call> = {}): Call {
  return makeCall({
    has_audio: true,
    audio_missing_reason: null,
    audio: {
      available: false,
      duration_mismatch: false,
      expired_at: '2026-09-01T10:00:00+05:00',
      capture_route: 'oem_file_harvest',
    },
    ...overrides,
  })
}

function page(items: Call[], overrides: Partial<CallPage> = {}): CallPage {
  return { items, next_cursor: null, has_more: false, total: items.length, ...overrides }
}

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Route every request to the handler, so a page that fires two queries does
 *  not depend on the order they resolve in. */
function respond(handler: (url: string) => Response) {
  fetchMock.mockImplementation((input) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
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

function renderPage(initialPath = '/calls') {
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
          <Route path="/calls" element={<CallsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Every `/calls` request the page made, in order. */
function callsRequests(): string[] {
  return fetchMock.mock.calls
    .map(([input]) =>
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url,
    )
    .filter((url) => url.includes('/api/v1/calls'))
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  signIn([Perm.CALLS_READ])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('call list', () => {
  it('renders a row per call from the mocked response', async () => {
    respond(() =>
      jsonResponse(
        200,
        page([
          makeCall({ id: 'a', seq: 2, remote_number: '+998901112233' }),
          makeCall({
            id: 'b',
            seq: 1,
            direction: 'outgoing',
            disposition: 'no_answer',
            duration_sec: 0,
            answered_at: null,
            remote_number: '901234567',
          }),
        ]),
      ),
    )

    renderPage()

    // The number is rendered in the readable local form, not as it arrived.
    expect(await screen.findByText('+998 90 111 22 33')).toBeInTheDocument()
    expect(screen.getByText('90 123 45 67')).toBeInTheDocument()

    expect(screen.getAllByRole('row')).toHaveLength(3) // header + two calls

    // Scoped to the table: the same words are also the filter bar's <option>
    // labels, which is the point of deriving both from one label map.
    const table = screen.getByRole('table')
    expect(within(table).getByText(t('calls.direction.incoming'))).toBeInTheDocument()
    expect(within(table).getByText(t('calls.direction.outgoing'))).toBeInTheDocument()
    expect(within(table).getByText('02:00')).toBeInTheDocument()
    expect(within(table).getByText('00:00')).toBeInTheDocument()
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * The customer's name is a column, not a footnote.
   *
   * It used to be a grey suffix inside the number cell, at `text-xs` beside a
   * monospace number, which is easy to miss entirely — and it is the thing
   * people scan this list for. Asserted by COLUMN INDEX rather than by "the
   * text is somewhere in the row", because "somewhere in the row" is exactly
   * what it was before.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('renders the contact name in its own column, and a dash where there is none', async () => {
    respond(() =>
      jsonResponse(
        200,
        page([
          makeCall({ id: 'named', contact_name: 'Nodira Yusupova' }),
          makeCall({ id: 'unknown', contact_name: null }),
        ]),
      ),
    )

    renderPage()

    const table = await screen.findByRole('table')
    const [header, named, unknown] = within(table).getAllByRole('row')
    const columns = within(header as HTMLElement)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent)
    const contactColumn = columns.indexOf(t('calls.colContact'))
    expect(contactColumn).toBeGreaterThan(-1)

    const namedCell = within(named as HTMLElement).getAllByRole('cell')[contactColumn]
    expect(namedCell).toHaveTextContent('Nodira Yusupova')
    // The full name is on the cell even when the column truncates it.
    expect(namedCell).toHaveAttribute('title', 'Nodira Yusupova')

    // An absent value is the em dash the rest of the product uses, never a
    // blank cell (`shared/ui/detail.tsx`).
    expect(within(unknown as HTMLElement).getAllByRole('cell')[contactColumn]).toHaveTextContent('—')

    // And it is not rendered twice: the number cell keeps the number only.
    const numberColumn = columns.indexOf(t('calls.colRemote'))
    expect(within(named as HTMLElement).getAllByRole('cell')[numberColumn]).not.toHaveTextContent(
      'Nodira Yusupova',
    )
  })

  it('shows the contact column to an own-scope user too', async () => {
    signIn([Perm.CALLS_READ_OWN])
    respond(() => jsonResponse(200, page([makeCall({ contact_name: 'Nodira Yusupova' })])))

    renderPage()

    const header = (await screen.findAllByRole('row'))[0]
    expect(header).toBeDefined()
    expect(within(header as HTMLElement).getByText(t('calls.colContact'))).toBeInTheDocument()
    expect(within(header as HTMLElement).queryByText(t('calls.colAgent'))).toBeNull()
  })

  /**
   * The column ORDER, pinned. A header and a cell that drift apart is a table
   * that lies — and moving a column is a two-place edit that looks like a
   * one-place edit, so it is exactly the change a test has to catch.
   */
  it('lays out the columns in the agreed order, headers and cells together', async () => {
    respond(() =>
      jsonResponse(
        200,
        page([makeCall({ agent_name: 'Aziz Karimov', contact_name: 'Nodira Yusupova' })]),
      ),
    )

    renderPage()

    const table = await screen.findByRole('table')
    const [header, row] = within(table).getAllByRole('row')
    expect(
      within(header as HTMLElement)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent),
    ).toEqual([
      t('calls.colTime'),
      t('calls.colReceived'),
      t('calls.colAgent'),
      t('calls.colDirection'),
      t('calls.colRemote'),
      t('calls.colContact'),
      t('calls.colStatus'),
      t('calls.colDuration'),
      t('calls.colAudio'),
    ])

    const cells = within(row as HTMLElement).getAllByRole('cell')
    expect(cells).toHaveLength(9)
    expect(cells[2]).toHaveTextContent('Aziz Karimov')
    expect(cells[5]).toHaveTextContent('Nodira Yusupova')
  })

  it('closes the eight remaining columns up when the agent column is hidden', async () => {
    signIn([Perm.CALLS_READ_OWN])
    respond(() => jsonResponse(200, page([makeCall({ contact_name: 'Nodira Yusupova' })])))

    renderPage()

    const table = await screen.findByRole('table')
    const [header, row] = within(table).getAllByRole('row')
    expect(
      within(header as HTMLElement)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent),
    ).toEqual([
      t('calls.colTime'),
      t('calls.colReceived'),
      t('calls.colDirection'),
      t('calls.colRemote'),
      t('calls.colContact'),
      t('calls.colStatus'),
      t('calls.colDuration'),
      t('calls.colAudio'),
    ])
    expect(within(row as HTMLElement).getAllByRole('cell')).toHaveLength(8)
  })

  it('shows WHY a call has no recording rather than an empty cell (UC-14)', async () => {
    respond(() => jsonResponse(200, page([callWithoutAudio('oem_recorder_off')])))

    renderPage()

    const table = await screen.findByRole('table')
    expect(
      within(table).getByText(t('calls.noAudioReason.oem_recorder_off')),
    ).toBeInTheDocument()
    expect(within(table).queryByText(t('calls.audio.present'))).toBeNull()
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * The distinction this suite exists to protect.
   *
   * `audio.available === false` means two opposite things, and only one of
   * them is somebody's fault. Rendering both as "no recording" would put
   * normal 12-month retention into the gap report's numerator — the report
   * Bonvi uses to decide whether a handset or a person has a problem. Getting
   * it wrong points at the wrong person, so it gets its own test.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('never renders retention and capture failure as the same thing', async () => {
    respond(() =>
      jsonResponse(
        200,
        page([
          callWithExpiredAudio({ id: 'expired' }),
          callWithoutAudio('no_permission', { id: 'failed' }),
        ]),
      ),
    )

    renderPage()

    const table = await screen.findByRole('table')
    // The recording existed and retention removed it: the system working.
    expect(within(table).getByText(t('calls.audio.expired'))).toBeInTheDocument()
    // The recording never existed: a capture failure.
    expect(
      within(table).getByText(t('calls.noAudioReason.no_permission')),
    ).toBeInTheDocument()

    // Neither is allowed to borrow the other's words.
    expect(t('calls.audio.expired')).not.toBe(t('calls.audio.missing'))
    const rows = within(table).getAllByRole('row').slice(1)
    const [expiredRow, failedRow] = rows
    expect(expiredRow?.textContent).not.toContain(t('calls.noAudioReason.no_permission'))
    expect(failedRow?.textContent).not.toContain(t('calls.audio.expired'))
  })

  it('prints the agent name the server resolved, never a bare id', async () => {
    respond(() => jsonResponse(200, page([makeCall({ agent_name: 'Aziz Karimov' })])))

    renderPage()

    const table = await screen.findByRole('table')
    expect(within(table).getByText('Aziz Karimov')).toBeInTheDocument()
    // No second request for a roster the row already carries: looking the name
    // up per row is the N+1 problem relocated to the browser.
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).includes('/api/v1/agents')),
    ).toHaveLength(0)
  })

  it('renders the loading state before the response arrives', async () => {
    let release: ((response: Response) => void) | undefined
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => { release = resolve }),
    )

    renderPage()

    expect(screen.getByTestId('query-loading')).toBeInTheDocument()
    release?.(jsonResponse(200, page([makeCall()])))
    await waitFor(() => expect(screen.queryByTestId('query-loading')).toBeNull())
  })

  it('distinguishes "no calls yet" from "nothing matches this filter"', async () => {
    respond(() => jsonResponse(200, page([])))

    const { unmount } = renderPage()
    expect(await screen.findByText(t('calls.emptyAll'))).toBeInTheDocument()
    unmount()

    renderPage('/calls?has_audio=false')
    expect(await screen.findByText(t('calls.emptyFiltered'))).toBeInTheDocument()
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
    // Neither the machine code nor the server's English wording reaches a user.
    expect(screen.queryByText('forbidden')).toBeNull()
    expect(screen.queryByText('Forbidden')).toBeNull()
  })
})

describe('filters', () => {
  it('reads the filters out of the URL and sends the server its own names', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage(
      `/calls?agent_id=${AGENT_ID}&direction=incoming&disposition=answered` +
        '&call_type=external&has_audio=false&date_from=2026-09-01&date_to=2026-09-05' +
        '&search=Nodira',
    )

    await screen.findByRole('table')
    const url = callsRequests()[0] ?? ''
    // `agent_id` is a repeated parameter on the wire, not a comma-joined
    // string: the server declares `list[UUID]` and would 422 on the latter.
    expect(url).toContain(`agent_id=${AGENT_ID}`)
    expect(url).toContain('direction=incoming')
    expect(url).toContain('disposition=answered')
    expect(url).toContain('call_type=external')
    expect(url).toContain('has_audio=false')
    expect(url).toContain('date_from=2026-09-01')
    expect(url).toContain('date_to=2026-09-05')
    // `search` is the panel's own parameter — the ONE box — and the server
    // receives whichever of its two it turned out to be (`./search.ts`).
    expect(url).toContain('q=Nodira')
    expect(url).not.toContain('search=')
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * The "Turi" filter offers two values, not three.
   *
   * `unknown` is a real stored value and stays everywhere else — SPEC §10.2
   * makes it the mandatory default for a call the line directory cannot
   * classify, and the detail page still badges it. The client asked for the
   * FILTER not to offer it, and `CALL_TYPE_FILTER_LABEL` is where that
   * narrowing is written down. This test is what stops somebody reading the
   * divergence from `CALL_TYPE_LABEL` as a bug and "fixing" it back.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('offers internal and external as call types, and not "unknown"', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')

    const select = screen.getByLabelText(t('calls.filterCallType'))
    expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual([
      t('calls.filterAny'),
      t('calls.type.internal'),
      t('calls.type.external'),
    ])
    expect(within(select).queryByText(t('calls.type.unknown'))).toBeNull()
  })

  it('does not forward a call type it cannot show', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    // The page sends only what its own control can display, so a link asking
    // for the withdrawn value is no filter rather than a filter with nothing
    // selected in the box.
    renderPage('/calls?call_type=unknown')

    await screen.findByRole('table')
    expect(callsRequests()[0] ?? '').not.toContain('call_type=')
  })

  it('ignores a filter value the server does not accept', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    // A hand-edited or stale link. Forwarding it would be a 422 the reader
    // cannot act on; dropping it shows the unfiltered list, which they can.
    renderPage('/calls?direction=sideways')

    await screen.findByRole('table')
    expect(callsRequests()[0] ?? '').not.toContain('direction=')
  })

  it('clears every filter at once, leaving none behind', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?direction=incoming&search=Nodira&has_audio=false&date_from=2026-09-01')
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: t('calls.filterReset') }))

    await waitFor(() => expect(callsRequests().length).toBeGreaterThan(1))
    const url = callsRequests().at(-1) ?? ''
    expect(url).not.toContain('direction=')
    expect(url).not.toContain('q=')
    expect(url).not.toContain('remote_number=')
    expect(url).not.toContain('has_audio=')
    expect(url).not.toContain('date_from=')
  })

  it('says "nothing matches" rather than "no calls yet" once a filter is set', async () => {
    respond(() => jsonResponse(200, page([])))

    renderPage('/calls?direction=incoming')

    expect(await screen.findByText(t('calls.emptyFiltered'))).toBeInTheDocument()
    expect(screen.queryByText(t('calls.emptyAll'))).toBeNull()
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * Two date filters, not one range control.
   *
   * Each bound stands alone — the server reads a missing one as open-ended —
   * and each applies the moment it is picked. They only know about each other
   * through `min`/`max`, so the picker cannot offer a start after the end.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('reads both dates out of the URL and cross-constrains them', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?date_from=2026-09-01&date_to=2026-09-05')

    await screen.findByRole('table')
    const from = screen.getByLabelText(t('calls.filterDateFrom'))
    const to = screen.getByLabelText(t('calls.filterDateTo'))
    expect(from).toHaveValue('2026-09-01')
    expect(to).toHaveValue('2026-09-05')
    expect(from).toHaveAttribute('max', '2026-09-05')
    expect(to).toHaveAttribute('min', '2026-09-01')
  })

  it('applies a start date on its own, without waiting for an end date', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')

    // Picking a day in the calendar is the act of choosing; the filter runs
    // there and then, and "from this date" is a complete question by itself.
    fireEvent.change(screen.getByLabelText(t('calls.filterDateFrom')), {
      target: { value: '2026-09-01' },
    })

    await waitFor(() => expect(callsRequests().at(-1)).toContain('date_from=2026-09-01'))
    expect(callsRequests().at(-1) ?? '').not.toContain('date_to=')
  })

  it('applies an end date on its own too', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')

    fireEvent.change(screen.getByLabelText(t('calls.filterDateTo')), {
      target: { value: '2026-09-05' },
    })

    await waitFor(() => expect(callsRequests().at(-1)).toContain('date_to=2026-09-05'))
    expect(callsRequests().at(-1) ?? '').not.toContain('date_from=')
  })

  it('clears one bound without touching the other', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?date_from=2026-09-01&date_to=2026-09-05')
    await screen.findByRole('table')

    await userEvent.click(
      screen.getByRole('button', { name: t('calls.filterDateClearFrom') }),
    )

    await waitFor(() => expect(callsRequests().at(-1)).not.toContain('date_from='))
    expect(callsRequests().at(-1) ?? '').toContain('date_to=2026-09-05')
    expect(screen.getByLabelText(t('calls.filterDateTo'))).toHaveValue('2026-09-05')
  })
})

/**
 * ════════════════════════════════════════════════════════════════════════════
 * One box, two server parameters.
 *
 * The page used to carry "Kontakt nomi" (`q`) and "Raqam bo'yicha"
 * (`remote_number`) side by side and made the reader choose. It now has one
 * field and `../search.ts` chooses — that rule has its own unit test; what is
 * asserted here is the wiring: that the box reaches the URL, that the URL
 * reaches the right server parameter, and that the query still fires on intent
 * rather than on every keystroke.
 * ════════════════════════════════════════════════════════════════════════════
 */
describe('search', () => {
  function searchBox(): HTMLElement {
    return screen.getByRole('searchbox', { name: t('calls.search') })
  }

  it('offers one search box, not the two it replaced', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()

    await screen.findByRole('table')
    expect(screen.getAllByRole('searchbox')).toHaveLength(1)
    expect(searchBox()).toHaveAttribute('placeholder', t('calls.searchHint'))
    // The two labels the old pair carried are gone from the bar.
    expect(screen.queryByText(t('calls.filterContact'))).toBeNull()
    expect(screen.queryByText(t('calls.filterRemoteNumber'))).toBeNull()
  })

  it('sends typed text as the contact-name filter', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')

    await userEvent.type(searchBox(), 'Nodira{Enter}')

    await waitFor(() => expect(callsRequests().at(-1)).toContain('q=Nodira'))
    expect(callsRequests().at(-1) ?? '').not.toContain('remote_number=')
  })

  it('sends a typed number as the number filter, spacing and all', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')

    await userEvent.type(searchBox(), '90 111 22 33{Enter}')

    // `URLSearchParams` spells a space `+`, which the server reads back as a
    // space and `phone_key` then strips (N37).
    await waitFor(() => expect(callsRequests().at(-1)).toContain('remote_number=90+111+22+33'))
    // Not as a contact name: `q` is an ILIKE over `contact_name` and would
    // match nothing at all for a number.
    expect(callsRequests().at(-1) ?? '').not.toContain('q=')
  })

  /**
   * Deliberately not debounced (`shared/ui/filters.tsx`). Typing eight
   * characters must not be eight ILIKE scans of a 500k-row table.
   */
  it('does not query per keystroke', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')
    const before = callsRequests().length

    await userEvent.type(searchBox(), 'Nodira')
    expect(callsRequests().length).toBe(before)

    // Blur commits, exactly like Enter does.
    await userEvent.tab()
    await waitFor(() => expect(callsRequests().at(-1)).toContain('q=Nodira'))
  })

  it('puts the typed text in the URL, so the filtered list is a link', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?search=901112233')

    await screen.findByRole('table')
    expect(searchBox()).toHaveValue('901112233')
    expect(callsRequests()[0] ?? '').toContain('remote_number=901112233')
  })

  it('finds an extension, which only the number filter can match', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()
    await screen.findByRole('table')

    // `*700` has no phone key, so the server falls back to an exact match on
    // the raw string — the branch that finds extension calls. Sending it as
    // `q` would search contact names and find nothing.
    await userEvent.type(searchBox(), '*700{Enter}')

    // `URLSearchParams` leaves `*` literal; the server sees the raw string it
    // needs for the exact-match branch.
    await waitFor(() => expect(callsRequests().at(-1)).toContain('remote_number=*700'))
    expect(callsRequests().at(-1) ?? '').not.toContain('q=')
  })

  /**
   * ══════════════════════════════════════════════════════════════════════
   * Somebody's saved link still means what it meant.
   *
   * `q` and `remote_number` were the URL parameters until this page merged its
   * two boxes. A bookmark or a chat message carrying one of them must not open
   * an UNFILTERED list — that looks exactly like a filtered list that found a
   * lot, and nothing on screen says otherwise.
   * ══════════════════════════════════════════════════════════════════════
   */
  it('keeps an old ?q= link filtered', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?q=Nodira')

    await screen.findByRole('table')
    expect(searchBox()).toHaveValue('Nodira')
    expect(callsRequests()[0] ?? '').toContain('q=Nodira')
  })

  it('keeps an old ?remote_number= link filtered', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?remote_number=901112233')

    await screen.findByRole('table')
    expect(searchBox()).toHaveValue('901112233')
    expect(callsRequests()[0] ?? '').toContain('remote_number=901112233')
  })

  it('retires the legacy parameter as soon as the box is used', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?q=Nodira')
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: t('calls.searchClear') }))

    // If `q=` were left in the URL, the fallback would read it again on the
    // next render and the filter would come back from the dead.
    await waitFor(() => expect(callsRequests().at(-1)).not.toContain('q='))
  })
})

/**
 * ════════════════════════════════════════════════════════════════════════════
 * The count, and how long it is allowed to live.
 *
 * Only the first page asks for a total (SPEC §4.0), so every later page answers
 * `total: null`. With 50-row pages a reader reaches page two twenty times
 * sooner than with 1000, and watching "Jami: 742 ta" turn into a dash reads as
 * a number that got lost. Holding it costs no request; holding it across a
 * FILTER change would be a lie.
 * ════════════════════════════════════════════════════════════════════════════
 */
describe('the total', () => {
  const CURSOR = 'C1'

  function respondWithTotals() {
    respond((url) => {
      if (url.includes(`cursor=${CURSOR}`)) {
        return jsonResponse(200, page([makeCall({ id: 'p2' })], { total: null }))
      }
      // A different answer per filter, so a held count cannot pass for the
      // right one by accident.
      const total = url.includes('direction=incoming') ? 7 : 742
      return jsonResponse(
        200,
        page([makeCall({ id: 'p1' })], { next_cursor: CURSOR, has_more: true, total }),
      )
    })
  }

  it('stays on screen on page two, and is replaced when a filter changes', async () => {
    respondWithTotals()

    renderPage()
    expect(await screen.findByText(t('calls.total', { count: '742' }))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: t('calls.nextPage') }))
    await waitFor(() => expect(callsRequests().at(-1)).toContain(`cursor=${CURSOR}`))

    // The server sent `total: null` for this page and the panel did not ask it
    // to do otherwise — the count on screen is the one it already had.
    expect(screen.getByText(t('calls.total', { count: '742' }))).toBeInTheDocument()
    expect(callsRequests().at(-1) ?? '').toContain('with_total=false')

    await userEvent.selectOptions(
      screen.getByLabelText(t('calls.filterDirection')),
      'incoming',
    )

    // A count from the previous filter is worse than no count: 742 never
    // appears beside a filtered list.
    expect(await screen.findByText(t('calls.total', { count: '7' }))).toBeInTheDocument()
    expect(screen.queryByText(t('calls.total', { count: '742' }))).toBeNull()
  })
})

describe('pagination', () => {
  it('asks for the next page with a cursor and never with an offset', async () => {
    const NEXT_CURSOR = 'eyJrIjpbIjIwMjYtMDktMDVUMTQ6MDU6MzArMDU6MDAiLCJhIl19'
    respond((url) =>
      jsonResponse(
        200,
        url.includes(`cursor=${encodeURIComponent(NEXT_CURSOR)}`)
          ? page([makeCall({ id: 'p2' })], { total: null })
          : page([makeCall({ id: 'p1' })], {
              next_cursor: NEXT_CURSOR,
              has_more: true,
              total: 2,
            }),
      ),
    )

    renderPage()
    await screen.findByText(t('calls.nextPage'))

    const first = callsRequests()[0] ?? ''
    expect(first).toContain('limit=50')
    // The first page carries no cursor, and asks for the total exactly once —
    // per filter change, not per page (SPEC §4.0).
    expect(first).not.toContain('cursor=')
    expect(first).toContain('with_total=true')

    await userEvent.click(screen.getByRole('button', { name: t('calls.nextPage') }))

    await waitFor(() => expect(callsRequests().length).toBeGreaterThan(1))
    const second = callsRequests().at(-1) ?? ''
    expect(second).toContain(`cursor=${encodeURIComponent(NEXT_CURSOR)}`)
    expect(second).toContain('with_total=false')

    // Keyset, not offset. An OFFSET skips and repeats rows while calls keep
    // arriving, which is exactly what UC-19 forbids.
    for (const url of callsRequests()) {
      expect(url).not.toMatch(/[?&](offset|page|skip)=/)
    }
  })

  /**
   * The page size is a constant now, not a control. A link somebody saved
   * while the picker still existed must open the list, not a 1000-row page and
   * not an error — the parameter is simply ignored.
   */
  it('asks for a fixed 50 rows and ignores a page size left in an old link', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage('/calls?limit=1000&direction=incoming')

    await screen.findByRole('table')
    const url = callsRequests()[0] ?? ''
    expect(url).toContain('limit=50')
    expect(url).not.toContain('limit=1000')
    expect(url).toContain('direction=incoming')
  })

  it('disables "previous" on the first page', async () => {
    respond(() => jsonResponse(200, page([makeCall()], { has_more: true, next_cursor: 'C1' })))

    renderPage()

    expect(await screen.findByRole('button', { name: t('calls.prevPage') })).toBeDisabled()
  })
})

describe('scope', () => {
  it('hides the agent column from an own-scope user and asks for no agent list', async () => {
    signIn([Perm.CALLS_READ_OWN])
    respond(() => jsonResponse(200, page([makeCall()])))

    renderPage()

    await screen.findByText('+998 90 111 22 33')
    const header = screen.getAllByRole('row')[0]
    expect(header).toBeDefined()
    expect(within(header as HTMLElement).queryByText(t('calls.colAgent'))).toBeNull()
    // The narrowing itself is the SERVER's job (CONVENTIONS.md §11); the panel
    // only stops asking for a roster it may not read.
    expect(fetchMock.mock.calls.map(([input]) => String(input)).join(' ')).not.toContain(
      '/api/v1/agents',
    )
  })

  it('shows the agent column to a full-scope reader and offers the filter', async () => {
    signIn([Perm.CALLS_READ, Perm.AGENTS_READ])
    respond((url) =>
      url.includes('/api/v1/agents')
        ? jsonResponse(200, {
            items: [
              {
                id: AGENT_ID,
                full_name: 'Aziz Karimov',
                employee_code: null,
                color: '#6366f1',
                hired_at: null,
                note: null,
                is_active: true,
                archived_at: null,
                created_at: '2026-01-01T00:00:00+05:00',
              },
            ],
            total: 1,
          })
        : jsonResponse(200, page([makeCall()])),
    )

    renderPage()

    const header = (await screen.findAllByRole('row'))[0]
    expect(header).toBeDefined()
    expect(within(header as HTMLElement).getByText(t('calls.colAgent'))).toBeInTheDocument()
    // The roster is fetched only to fill the filter's option list; the row's
    // own `agent_name` is what the column renders.
    expect(await screen.findByRole('option', { name: 'Aziz Karimov' })).toBeInTheDocument()
  })
})

describe('the audio archive button', () => {
  it('is hidden from a reader who may not download recordings', async () => {
    respond(() => jsonResponse(200, page([makeCall()])))
    signIn([Perm.CALLS_READ])
    renderPage()
    await screen.findByText('+998 90 111 22 33')

    expect(screen.queryByRole('button', { name: /Ovoz/ })).toBeNull()
  })

  it('says how many recordings this page holds', async () => {
    respond(() =>
      jsonResponse(200, page([makeCall({ has_audio: true })])),
    )
    signIn([Perm.CALLS_READ, Perm.AUDIO_DOWNLOAD])
    renderPage()
    await screen.findByText('+998 90 111 22 33')

    const button = screen.getByRole('button', {
      name: t('calls.audioArchive', { count: 1 }),
    })
    expect(button).toBeEnabled()
  })

  it('refuses the click when the page holds none', async () => {
    /**
     * The case that reads as a broken download: an archive containing only
     * `manifest.csv`. It is the correct answer and it looks like a fault, so
     * the button says it before the click rather than the archive after it.
     */
    respond(() => jsonResponse(200, page([callWithoutAudio('not_expected')])))
    signIn([Perm.CALLS_READ, Perm.AUDIO_DOWNLOAD])
    renderPage()
    await screen.findByText(t('calls.audioArchiveNone'))

    expect(
      screen.getByRole('button', { name: t('calls.audioArchiveNone') }),
    ).toBeDisabled()
  })
})
