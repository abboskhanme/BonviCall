/**
 * The call card.
 *
 * Three things are pinned, and each one is a rule somebody could undo without
 * noticing:
 *
 *  1. **A player appears ONLY for a recording that is actually playable**, and
 *     its `src` is same-origin. The two other states must never get one: an
 *     expired recording answers 410, and a control somebody can press to
 *     receive an error teaches them the system is broken when it is not.
 *  2. **A call with no recording shows the reason** (UC-14), and a
 *     retention-expired one says it EXISTED — see the audio-state tests.
 *  3. **The note button is not rendered without `calls:note`** (CONVENTIONS.md
 *     §11 — the server still decides, but the panel does not show a door it
 *     knows is locked).
 *
 * Plus the 404 path, which is also the "this call is not yours" path (UC-21):
 * the server answers 404 rather than 403 so a salesperson cannot learn that a
 * colleague spoke to a given number, and the panel must not undo that by
 * wording the two differently.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CallDetailPage } from '@/modules/calls/CallDetailPage'
import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

type Call = components['schemas']['CallResponse']
type AudioMissingReason = components['schemas']['AudioMissingReason']

const CALL_ID = '22222222-2222-4222-8222-222222222222'

function makeCall(overrides: Partial<Call> = {}): Call {
  return {
    id: CALL_ID,
    seq: 7,
    agent_id: '11111111-1111-4111-8111-111111111111',
    number_id: '33333333-3333-4333-8333-333333333333',
    installation_id: '44444444-4444-4444-8444-444444444444',
    direction: 'outgoing',
    disposition: 'answered',
    call_type: 'external',
    remote_number: '+998901112233',
    remote_number_key: '901112233',
    contact_name: 'Dilshod',
    started_at: '2026-09-05T09:03:11Z',
    answered_at: '2026-09-05T09:03:20Z',
    ended_at: '2026-09-05T09:05:20Z',
    duration_sec: 120,
    ring_sec: 9,
    received_at: '2026-09-05T09:05:30Z',
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

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/**
 * The call as JSON, and anything under `/audio` as bytes.
 *
 * The audio request is a real one: the bridge fetches it with the header and
 * turns it into a blob, exactly as it does on an insecure origin.
 */
function respondJson(call: Call) {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    if (url.includes('/audio')) {
      return Promise.resolve(
        new Response(new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/ogg' }), {
          status: 200,
          headers: { 'Content-Type': 'audio/ogg' },
        }),
      )
    }
    return Promise.resolve(jsonResponse(200, call))
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
        initialEntries={[`/calls/${CALL_ID}`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/calls/:id" element={<CallDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  // jsdom implements neither, and the blob route needs both.
  URL.createObjectURL = vi.fn(() => 'blob:test-audio')
  URL.revokeObjectURL = vi.fn()
  tokenStore.set('test-token')
  signIn([Perm.CALLS_READ, Perm.CALLS_NOTE, Perm.AUDIO_PLAY, Perm.AUDIO_DOWNLOAD])
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('call card', () => {
  it('renders the metadata in Asia/Tashkent and the number in local form', async () => {
    respondJson(makeCall())

    renderPage()

    expect(await screen.findByText('+998 90 111 22 33')).toBeInTheDocument()
    expect(screen.getByText('Dilshod')).toBeInTheDocument()
    // 09:03 UTC is 14:03 in Tashkent, whatever the reader's browser thinks.
    expect(screen.getAllByText('05/09/2026 14:03').length).toBeGreaterThan(0)
    expect(screen.getAllByText('02:00').length).toBeGreaterThan(0)
  })

  it('renders a player for a playable recording, with a same-origin src', async () => {
    respondJson(makeCall())

    const { container } = renderPage()

    await screen.findByTestId('audio-ready')
    const audio = container.querySelector('audio')
    expect(audio).not.toBeNull()
    // Same-origin or the browser withholds Content-Range and seek breaks. In
    // this environment there is no Service Worker, so the bridge falls back to
    // fetch + blob: — which is the path a LAN http:// demo takes for real.
    const src = audio?.getAttribute('src') ?? ''
    expect(src.startsWith('blob:') || src.startsWith('/api/v1/calls/')).toBe(true)
    expect(src).not.toMatch(/^https?:\/\//)
  })

  it('states why there is no recording (UC-14)', async () => {
    respondJson(callWithoutAudio('no_permission'))

    renderPage()

    expect(
      await screen.findByText(t('calls.noAudioReason.no_permission')),
    ).toBeInTheDocument()
    expect(screen.queryByText(t('callDetail.playerPending'))).toBeNull()
    // A capture failure must not be described as retention.
    expect(screen.queryByText(t('calls.audio.expired'))).toBeNull()
  })

  it('says a retention-deleted recording EXISTED, and says nobody is at fault', async () => {
    respondJson(callWithExpiredAudio())

    renderPage()

    expect(await screen.findByText(t('calls.audio.expired'))).toBeInTheDocument()
    // The sentence names the date and says in so many words that this is the
    // system working, because "no recording" alone reads as a broken phone.
    expect(screen.getByText(/01\/09\/2026/)).toBeInTheDocument()
    // No capture reason is invented for a recording that was never missing.
    expect(screen.queryByText(t('calls.noAudioReason.no_permission'))).toBeNull()
    expect(screen.queryByText(t('calls.noAudioReasonUnknown'))).toBeNull()
  })

  it('keeps the capture route visible after retention removed the file', async () => {
    // The per-model capture rate is the M0 baseline and UC-23 compares against
    // it, so "which mechanism ran on this handset" must survive the deletion.
    respondJson(callWithExpiredAudio())

    renderPage()

    expect(
      await screen.findByText(t('calls.captureRoute.oem_file_harvest')),
    ).toBeInTheDocument()
  })

  it('offers NO player for a recording retention has removed', async () => {
    respondJson(callWithExpiredAudio())

    const { container } = renderPage()

    await screen.findByText(t('calls.audio.expired'))
    // Pressing it would answer 410 `audio_expired`, and somebody who does
    // that concludes the system is broken when it is working exactly as
    // designed.
    expect(container.querySelector('audio')).toBeNull()
    expect(screen.queryByTestId('audio-ready')).toBeNull()
  })

  it('offers NO player for a recording that never existed', async () => {
    respondJson(callWithoutAudio('oem_recorder_off'))

    const { container } = renderPage()

    await screen.findByText(t('calls.noAudioReason.oem_recorder_off'))
    expect(container.querySelector('audio')).toBeNull()
  })

  it('renders the Uzbek sentence for a 404, which is also the wrong-owner answer', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(404, { error: { code: 'call_not_found', message: 'Not Found' } }),
    )

    renderPage()

    expect(await screen.findByTestId('query-error')).toBeInTheDocument()
    expect(screen.getByText(t('errors.call_not_found'))).toBeInTheDocument()
    expect(screen.queryByText('Not Found')).toBeNull()
  })
})

describe('note permission', () => {
  it('offers the edit button to a holder of calls:note', async () => {
    respondJson(makeCall())

    renderPage()

    expect(
      await screen.findByRole('button', { name: t('callDetail.noteEdit') }),
    ).toBeInTheDocument()
  })

  it('does not render the control at all without it', async () => {
    signIn([Perm.CALLS_READ])
    respondJson(makeCall())

    renderPage()

    expect(await screen.findByText(t('callDetail.noteEmpty'))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('callDetail.noteEdit') })).toBeNull()
  })
})
