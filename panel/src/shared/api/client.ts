/**
 * The one HTTP client. Every request in the panel goes through here
 * (CONVENTIONS-CLIENT.md §2), so the token, the refresh dance, the §9 envelope
 * and the base URL are decided once.
 *
 * Check: `grep -rn "fetch(" panel/src --include=*.ts*` returns this file and
 * the audio Service Worker (T153) and nothing else. ESLint enforces it.
 */
import {
  ApiError,
  CLIENT_ERROR_CODE,
  parseEnvelope,
  type ErrorDetail,
} from './errors'

/**
 * Empty means same-origin, and same-origin is the normal case: in production
 * Caddy serves the panel and the API from one host; in development the Vite
 * proxy forwards `/api` to the backend container. The audio endpoint MUST be
 * same-origin or the browser withholds `Content-Range` from both JS and the
 * Service Worker and seek breaks (CONVENTIONS-CLIENT.md §4).
 */
export const API_ORIGIN = import.meta.env.VITE_API_BASE_URL ?? ''

/** The panel surface. The device and service surfaces are not reachable here. */
export const API_PREFIX = '/api/v1'

const REFRESH_PATH = '/auth/refresh'
const LOGIN_PATH = '/auth/login'

/**
 * The access token lives in memory only.
 *
 * The refresh token is an HttpOnly cookie scoped to `/api/v1/auth/refresh`
 * (SPEC §4.7) — putting the access token in localStorage would hand back to
 * any XSS exactly what that cookie was chosen to protect. The cost is one
 * silent refresh on page load, which `restore()` in the auth store performs.
 */
let accessToken: string | null = null

type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler = () => {}

/**
 * Called when the session is over for good: refresh failed or was refused.
 * The auth store registers a handler that flips its status to `anonymous`;
 * the router's `Protected` then redirects to /login and remembers where the
 * user was. Deliberately a callback rather than an import, so that
 * client.ts depends on nothing.
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler
}

export const tokenStore = {
  get: (): string | null => accessToken,
  set: (token: string): void => {
    accessToken = token
  },
  clear: (): void => {
    accessToken = null
  },
}

export type QueryValue = string | number | boolean | null | undefined | readonly string[]
export type Query = Record<string, QueryValue>

export function buildUrl(path: string, query?: Query): string {
  const base = API_ORIGIN || (typeof window === 'undefined' ? 'http://localhost' : window.location.origin)
  const url = new URL(`${API_PREFIX}${path}`, base)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, String(item))
      } else {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return API_ORIGIN ? url.toString() : `${url.pathname}${url.search}`
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    // Not JSON. A proxy error page or a truncated body looks like this; the
    // caller falls back to a generic message rather than showing HTML.
    return null
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await readJson(response)
  const envelope = parseEnvelope(body)
  if (envelope) {
    return new ApiError(
      response.status,
      envelope.code,
      envelope.message ?? '',
      envelope.detail,
      envelope.requestId,
    )
  }
  return new ApiError(response.status, CLIENT_ERROR_CODE.MALFORMED, '')
}

/**
 * One refresh at a time.
 *
 * A page that fires six queries at once produces six simultaneous 401s when the
 * access token expires. Without this, six refresh calls race; the server treats
 * a replayed refresh token as theft (`refresh_reused`, SPEC §4.7) and logs
 * everybody out. They share one promise instead.
 */
let refreshInFlight: Promise<boolean> | null = null

interface RefreshResponse {
  access_token: string
}

async function performRefresh(): Promise<boolean> {
  try {
    const response = await fetch(buildUrl(REFRESH_PATH), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) return false
    const body = await readJson(response)
    if (
      typeof body === 'object' &&
      body !== null &&
      'access_token' in body &&
      typeof (body as RefreshResponse).access_token === 'string'
    ) {
      tokenStore.set((body as RefreshResponse).access_token)
      return true
    }
    return false
  } catch {
    // The network is down, not the session. Treat it as a failed refresh: the
    // caller reports the original 401 and the user logs in again once online.
    return false
  }
}

function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

/**
 * Ask for a new access token using the refresh cookie.
 *
 * The auth store calls this once on boot: the access token is memory-only, so
 * after a page reload the refresh cookie is the only evidence of a session.
 * Shares the in-flight promise with the mid-session retry above.
 */
export function refreshAccessToken(): Promise<boolean> {
  return refreshOnce()
}

function authHeader(): Record<string, string> {
  const token = tokenStore.get()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

interface SendOptions {
  method: string
  path: string
  query?: Query
  body?: BodyInit | null
  headers?: Record<string, string>
  /** Auth endpoints must not recurse through the refresh path. */
  allowRefresh?: boolean
}

async function send(options: SendOptions, isRetry = false): Promise<Response> {
  let response: Response
  try {
    response = await fetch(buildUrl(options.path, options.query), {
      method: options.method,
      credentials: 'include',
      headers: { ...options.headers, ...authHeader() },
      body: options.body ?? null,
    })
  } catch {
    throw new ApiError(0, CLIENT_ERROR_CODE.NETWORK, '')
  }

  if (response.status !== 401 || isRetry || options.allowRefresh === false) return response

  // The token expired mid-session. Refresh silently once and replay the
  // request; only when that fails does the user see a login screen.
  const refreshed = await refreshOnce()
  if (!refreshed) {
    tokenStore.clear()
    onUnauthorized()
    return response
  }
  return send(options, true)
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  const body = await readJson(response)
  return body as T
}

async function request<T>(options: SendOptions): Promise<T> {
  return unwrap<T>(await send(options))
}

function jsonBody(body: unknown): Pick<SendOptions, 'body' | 'headers'> {
  if (body === undefined) return { body: null, headers: {} }
  return {
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  }
}

/**
 * Multipart upload.
 *
 * `Content-Type` is NOT set here and must never be. `multipart/form-data`
 * carries a `boundary=…` parameter that only the browser knows, because
 * FormData picks the boundary at random. Writing the header by hand drops the
 * boundary, the server cannot split the body, and the failure surfaces as
 * "422: field required" — "I sent a file, but there is no file".
 */
async function postForm<T>(path: string, form: FormData, query?: Query): Promise<T> {
  return request<T>({ method: 'POST', path, query, body: form })
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>({ method: 'GET', path, query }),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>({ method: 'POST', path, query, ...jsonBody(body) }),
  put: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>({ method: 'PUT', path, query, ...jsonBody(body) }),
  patch: <T>(path: string, body?: unknown, query?: Query) =>
    request<T>({ method: 'PATCH', path, query, ...jsonBody(body) }),
  delete: <T>(path: string, query?: Query) => request<T>({ method: 'DELETE', path, query }),
  postForm,
  /** Login and refresh answer 401 as a normal outcome; refreshing on them
   *  would loop. */
  postWithoutRefresh: <T>(path: string, body?: unknown) =>
    request<T>({ method: 'POST', path, allowRefresh: false, ...jsonBody(body) }),
}

export { ApiError, LOGIN_PATH, REFRESH_PATH }
export type { ErrorDetail }
