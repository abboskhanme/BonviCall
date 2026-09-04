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
import { render, screen, waitFor, within } from '@testing-library/react'
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
        '&remote_number=901112233&q=Nodira',
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
    expect(url).toContain('remote_number=901112233')
    expect(url).toContain('q=Nodira')
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

    renderPage('/calls?direction=incoming&q=Nodira&has_audio=false')
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: t('calls.filterReset') }))

    await waitFor(() => expect(callsRequests().length).toBeGreaterThan(1))
    const url = callsRequests().at(-1) ?? ''
    expect(url).not.toContain('direction=')
    expect(url).not.toContain('q=')
    expect(url).not.toContain('has_audio=')
  })

  it('says "nothing matches" rather than "no calls yet" once a filter is set', async () => {
    respond(() => jsonResponse(200, page([])))

    renderPage('/calls?direction=incoming')

    expect(await screen.findByText(t('calls.emptyFiltered'))).toBeInTheDocument()
    expect(screen.queryByText(t('calls.emptyAll'))).toBeNull()
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
    expect(first).toContain('limit=')
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
