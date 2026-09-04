/**
 * Playing a recording that lives behind a bearer token.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * `GET /api/v1/calls/{id}/audio` requires an `Authorization` header, and
 * `<audio src>` cannot send one. That single fact makes "token-protected" and
 * "seekable" mutually exclusive unless something sits in between. Two routes
 * exist and BOTH are required (CONVENTIONS-CLIENT.md §4):
 *
 *   **Service Worker (preferred).** `public/audio-sw.js` intercepts the
 *   request and adds the header. The `<audio>` element opens an ordinary URL,
 *   issues its own `Range` requests, gets 206s back, and seek is native — the
 *   browser never downloads more than the listener actually reaches.
 *
 *   **fetch + blob: (fallback).** Where a Service Worker is unavailable — an
 *   insecure origin, which is what a LAN `http://` demo is, or an old browser
 *   — the file is fetched with the header and handed to the player as a blob
 *   URL. Seek still works, but the whole file downloads first. This path is
 *   not optional politeness; it is what keeps a demo working on a laptop
 *   plugged into an office switch.
 *
 * **The URL is always same-origin.** Cross-origin, the browser withholds
 * `Content-Range` from both JS and the Service Worker's response, and seek
 * breaks with no error anybody can see. `/api` reaches the server through the
 * Vite proxy in development and through Caddy in production, so the header
 * survives.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { tokenStore } from '@/shared/api/client'

/** The path the Service Worker watches for. Keep in step with `AUDIO_PATH`
 *  in `public/audio-sw.js`. */
export function callAudioPath(callId: string): string {
  return `/api/v1/calls/${callId}/audio`
}

/**
 * The address to stream from.
 *
 * `CallAudioSummary.url` is a server-supplied **path**, never signed and never
 * public (N20). It is used when present, but only after checking it really is
 * a path: an absolute URL here would be cross-origin, and cross-origin is
 * precisely the thing that silently breaks seek. A value that is not a
 * same-origin path is ignored in favour of the canonical one rather than
 * trusted, because the failure it causes is invisible.
 */
export function resolveAudioUrl(callId: string, url: string | null | undefined): string {
  if (typeof url === 'string' && url.startsWith('/') && !url.startsWith('//')) return url
  return callAudioPath(callId)
}

const SW_SCRIPT = '/audio-sw.js'
const TOKEN_MESSAGE = 'bonvicall-audio-token'

export type BridgeMode = 'service-worker' | 'blob'

function serviceWorkerUsable(): boolean {
  // `isSecureContext` is the real gate: https, or localhost. A LAN http://
  // origin has no Service Worker at all, which is the fallback's whole reason.
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    typeof window !== 'undefined' &&
    window.isSecureContext
  )
}

let registration: Promise<ServiceWorkerRegistration | null> | null = null

function register(): Promise<ServiceWorkerRegistration | null> {
  if (!serviceWorkerUsable()) return Promise.resolve(null)
  registration ??= navigator.serviceWorker
    .register(SW_SCRIPT)
    .then(() => navigator.serviceWorker.ready)
    .catch(() => {
      // A refused registration is a fallback, not an error the user should
      // read about: the blob path still plays the recording.
      registration = null
      return null
    })
  return registration
}

/**
 * Hand the worker the current access token and **wait for it to confirm**.
 *
 * The acknowledgement is the point. `postMessage` is fire-and-forget, so
 * without the round trip the first play can leave before the token lands and
 * come back 401 — which `<audio>` surfaces only as a generic `error` event
 * with no status attached, i.e. the least debuggable failure in the browser.
 */
async function sendToken(worker: ServiceWorker): Promise<boolean> {
  const token = tokenStore.get()
  if (!token) return false

  return new Promise<boolean>((resolve) => {
    const channel = new MessageChannel()
    const timer = window.setTimeout(() => resolve(false), 2000)
    channel.port1.onmessage = (event: MessageEvent<{ ok?: boolean }>) => {
      window.clearTimeout(timer)
      resolve(event.data?.ok === true)
    }
    worker.postMessage({ type: TOKEN_MESSAGE, token }, [channel.port2])
  })
}

/**
 * Get a playable URL for this recording, and say which route produced it.
 *
 * `revoke` exists because the blob path allocates: without calling it the
 * object URL — and the whole downloaded file behind it — stays in memory
 * until the tab closes.
 */
export interface AudioSource {
  url: string
  mode: BridgeMode
  revoke: () => void
}

export async function openAudio(callId: string, serverUrl?: string | null): Promise<AudioSource> {
  const path = resolveAudioUrl(callId, serverUrl)

  const ready = await register()
  const worker = ready?.active ?? navigator.serviceWorker?.controller ?? null
  if (worker && (await sendToken(worker))) {
    // The player fetches this itself; the worker adds the header in flight.
    return { url: path, mode: 'service-worker', revoke: () => {} }
  }

  const response = await authorisedFetch(path)
  if (!response.ok) throw new AudioError(response.status)
  const objectUrl = URL.createObjectURL(await response.blob())
  return {
    url: objectUrl,
    mode: 'blob',
    revoke: () => URL.revokeObjectURL(objectUrl),
  }
}

/** The status behind a failed load, so the page can say something specific.
 *  410 is `audio_expired`, 404 is a wrong owner, 401 is a dead session. */
export class AudioError extends Error {
  readonly status: number
  constructor(status: number) {
    super(`audio_request_failed_${status}`)
    this.name = 'AudioError'
    this.status = status
  }
}

/**
 * The one place outside `shared/api/client.ts` that calls `fetch`, and it is
 * deliberate: this is a binary stream with a `Range` header and a
 * `Content-Disposition` to read, none of which the JSON client models. The
 * ESLint exemption names this file for that reason.
 */
async function authorisedFetch(path: string, extra?: Record<string, string>): Promise<Response> {
  const token = tokenStore.get()
  return fetch(path, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...extra,
    },
    credentials: 'include',
    cache: 'no-store',
  })
}

/**
 * Save the recording to a file.
 *
 * A plain `<a download>` does NOT work: the endpoint wants an `Authorization`
 * header and a browser following a link does not send one.
 *
 * **The filename comes from the server's `Content-Disposition`**, never built
 * here. Building it client-side would put the naming rule in two places, and
 * the two would drift — SPEC §4.8 fixes the format server-side precisely so
 * that an exported file and a downloaded one agree.
 */
export async function downloadCallAudio(callId: string, serverUrl?: string | null): Promise<void> {
  const path = `${resolveAudioUrl(callId, serverUrl)}?download=true`
  const response = await authorisedFetch(path)
  if (!response.ok) throw new AudioError(response.status)

  const objectUrl = URL.createObjectURL(await response.blob())
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filenameFrom(response.headers.get('content-disposition'))
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    // Not revoking leaves the entire file in memory until the tab closes.
    URL.revokeObjectURL(objectUrl)
  }
}

/**
 * `filename*` wins over `filename`: the starred form carries UTF-8, so an
 * agent's name survives, while the plain form is the ASCII fallback with the
 * non-Latin characters already stripped.
 */
export function filenameFrom(header: string | null): string {
  if (!header) return 'call.ogg'
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // Malformed encoding from a proxy that rewrote the header; fall through
      // to the plain form rather than showing the user a percent-escaped mess.
    }
  }
  return /filename="([^"]+)"/i.exec(header)?.[1] ?? 'call.ogg'
}
