/* ══════════════════════════════════════════════════════════════════════════
   The audio authorisation bridge (T153, N43, SPEC §4.8).

   THE PROBLEM
   `<audio src="…">` cannot carry an `Authorization` header. The browser API
   simply does not allow it, and `GET /api/v1/calls/{id}/audio` requires a
   bearer token — so a plain `src` is always 401.

   WHY fetch + blob: IS NOT ENOUGH
   A blob downloads the whole file first and seeks inside memory. On a
   twenty-minute recording, a manager jumping to minute eighteen waits for all
   of it, and the server never sees a single `Range` request. What we want is
   the opposite: the browser's own player issuing real 206 requests.

   THE SOLUTION
   This worker intercepts requests leaving the page and adds the header to
   EXACTLY ONE path — `/api/v1/calls/<uuid>/audio`. The `<audio>` element
   knows nothing about it: it opens an ordinary URL, asks for a Range, gets a
   206, and native seek works.

   Nothing else is touched (`respondWith` is not called for any other request)
   and nothing is cached: `cache: 'no-store'` keeps the rule that recordings
   are never stored on the panel's side.

   Ported from ../BonviZvonki/services/web/public/audio-sw.js, with its
   comments translated — CONVENTIONS.md §14 does not follow that repo into
   Uzbek comments, and copying a file brings its comment language with it.
   ══════════════════════════════════════════════════════════════════════════ */

const AUDIO_PATH = /^\/api\/v1\/calls\/[0-9a-fA-F-]{36}\/audio$/

/** Memory only. If the worker is stopped, the page re-sends it on next play. */
let accessToken = null

self.addEventListener('install', () => {
  // Take over immediately rather than waiting for the old worker to be
  // released; a stale bridge is one that has an expired token.
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // Claim on first registration, or the bridge would do nothing until the
  // user happened to reload the page.
  event.waitUntil(self.clients.claim())
})

self.addEventListener('message', (event) => {
  const data = event.data
  if (!data || data.type !== 'bonvicall-audio-token') return

  accessToken = data.token || null

  // The page WAITS for this acknowledgement. Without it the first "play"
  // could leave before the token arrived and come back 401, which the
  // `<audio>` element reports only as a generic error.
  const port = event.ports && event.ports[0]
  if (port) port.postMessage({ ok: true })
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  let url
  try {
    url = new URL(request.url)
  } catch {
    return
  }

  // Same-origin audio only. Everything else — HMR, images, the rest of the
  // API — passes through untouched.
  if (url.origin !== self.location.origin) return
  if (!AUDIO_PATH.test(url.pathname)) return

  event.respondWith(withAuthorization(request))
})

async function withAuthorization(request) {
  const headers = new Headers()

  // `Range` is forwarded UNCHANGED. Seek depends entirely on this header
  // reaching the server exactly as the player wrote it.
  const range = request.headers.get('range')
  if (range) headers.set('Range', range)

  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  return fetch(
    new Request(request.url, {
      method: 'GET',
      headers,
      mode: 'same-origin',
      credentials: 'include',
      cache: 'no-store',
      redirect: 'follow',
    }),
  )
}
