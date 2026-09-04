/**
 * The API client and the §9 error envelope.
 *
 * What is pinned here is the contract every page depends on: a failure must
 * arrive as an `ApiError` carrying the server's `code`, because the panel
 * branches on `code` and never on `message` (SPEC §4.0).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, setUnauthorizedHandler, tokenStore } from '@/shared/api/client'
import { ApiError, hasCode, messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Stands in for whatever Uzbek sentence the server sent. Kept as an opaque
 *  token because §14 allows Uzbek text in uz.json and nowhere else. */
const SERVER_TEXT = 'server-supplied-message'

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.clear()
  setUnauthorizedHandler(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('error envelope', () => {
  it('surfaces the code from {"error":{"code","message"}}', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, {
        error: {
          code: 'number_already_assigned',
          message: SERVER_TEXT,
          detail: { holder: 'Aziz' },
          request_id: '01J9ABC',
        },
      }),
    )

    const error = await api.get('/numbers').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.code).toBe('number_already_assigned')
    expect(apiError.status).toBe(409)
    expect(apiError.detail).toEqual({ holder: 'Aziz' })
    expect(apiError.requestId).toBe('01J9ABC')
    // Type-safe branching: a misspelled code would not compile.
    expect(hasCode(apiError, 'number_already_assigned')).toBe(true)
    expect(hasCode(apiError, 'not_found')).toBe(false)
  })

  it('renders the Uzbek catalogue entry for the code, not the raw message', () => {
    const error = new ApiError(403, 'forbidden', 'Forbidden')
    // The catalogue wins over the server's own wording, so the panel reads
    // the same for a code whatever surface produced it.
    expect(messageForError(error)).toBe(t('errors.forbidden'))
    expect(messageForError(error)).not.toBe('Forbidden')
  })

  it('falls back to the server message for a code the panel does not know yet', () => {
    const error = new ApiError(409, 'some_new_server_code', SERVER_TEXT)
    expect(messageForError(error)).toBe(SERVER_TEXT)
  })

  it('does not choke on a response that is not the envelope', async () => {
    fetchMock.mockResolvedValue(new Response('<html>502</html>', { status: 502 }))

    const error = (await api.get('/calls').catch((caught: unknown) => caught)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
    expect(messageForError(error)).toBe(t('errors.unknown'))
  })

  it('reports a dead network as a client-side code, never as a crash', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    const error = (await api.get('/calls').catch((caught: unknown) => caught)) as ApiError

    expect(error.status).toBe(0)
    expect(messageForError(error)).toBe(t('errors.network'))
  })
})

describe('token handling', () => {
  it('sends the bearer token when there is one', async () => {
    tokenStore.set('abc123')
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [] }))

    await api.get('/calls')

    const init = fetchMock.mock.calls[0]?.[1]
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer abc123')
  })

  it('refreshes once on a mid-session 401 and replays the request', async () => {
    tokenStore.set('expired')
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: 'unauthorized', message: '' } }))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh', token_type: 'bearer' }))
      .mockResolvedValueOnce(jsonResponse(200, { id: 'call-1' }))

    const result = await api.get<{ id: string }>('/calls/call-1')

    expect(result).toEqual({ id: 'call-1' })
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/api/v1/auth/refresh')
    expect(tokenStore.get()).toBe('fresh')
  })

  it('clears the session and notifies the app when the refresh is refused', async () => {
    tokenStore.set('expired')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: 'unauthorized', message: '' } }))
      .mockResolvedValueOnce(jsonResponse(401, { error: { code: 'refresh_reused', message: '' } }))

    const error = (await api.get('/calls').catch((caught: unknown) => caught)) as ApiError

    expect(error.status).toBe(401)
    expect(tokenStore.get()).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('never sets Content-Type on multipart — the boundary is the browser’s', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }))
    const form = new FormData()
    form.append('file', new Blob(['x']), 'app.apk')

    await api.postForm('/app-versions', form)

    const init = fetchMock.mock.calls[0]?.[1]
    expect(new Headers(init?.headers).has('Content-Type')).toBe(false)
  })
})
