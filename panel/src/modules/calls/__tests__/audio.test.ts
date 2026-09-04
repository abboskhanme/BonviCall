/**
 * The audio bridge's pure parts.
 *
 * Both functions here guard a failure that is invisible when it happens, which
 * is why they are tested rather than trusted:
 *
 *   `resolveAudioUrl` — a cross-origin URL breaks seek and NOTHING says so.
 *   The browser withholds `Content-Range` from JS and from the Service
 *   Worker's response, the player silently loses the ability to jump, and the
 *   only symptom is a scrub bar that does not move.
 *
 *   `filenameFrom` — the name comes from the server so that the export and the
 *   download cannot drift (SPEC §4.8). Building it client-side would put the
 *   rule in two places.
 */
import { describe, expect, it } from 'vitest'

import { callAudioPath, filenameFrom, resolveAudioUrl } from '@/modules/calls/audio'

const CALL_ID = '22222222-2222-4222-8222-222222222222'

describe('resolveAudioUrl', () => {
  it('uses the path the server supplied', () => {
    expect(resolveAudioUrl(CALL_ID, `/api/v1/calls/${CALL_ID}/audio`)).toBe(
      `/api/v1/calls/${CALL_ID}/audio`,
    )
  })

  it('falls back to the canonical path when the server sent nothing', () => {
    expect(resolveAudioUrl(CALL_ID, null)).toBe(callAudioPath(CALL_ID))
    expect(resolveAudioUrl(CALL_ID, undefined)).toBe(callAudioPath(CALL_ID))
    expect(resolveAudioUrl(CALL_ID, '')).toBe(callAudioPath(CALL_ID))
  })

  it('refuses an absolute URL, because cross-origin silently breaks seek', () => {
    // N20 says the url is a path, never signed and never public. If one ever
    // arrives absolute, using it would cost native seek with no error anyone
    // can see — so the canonical same-origin path wins instead.
    expect(resolveAudioUrl(CALL_ID, 'https://cdn.example.com/audio.ogg')).toBe(
      callAudioPath(CALL_ID),
    )
    expect(resolveAudioUrl(CALL_ID, 'http://localhost:9000/x.ogg')).toBe(callAudioPath(CALL_ID))
  })

  it('refuses a protocol-relative URL, which is cross-origin in disguise', () => {
    expect(resolveAudioUrl(CALL_ID, '//evil.example.com/x.ogg')).toBe(callAudioPath(CALL_ID))
  })

  it('produces a path the Service Worker will actually intercept', () => {
    // Keep in step with AUDIO_PATH in public/audio-sw.js: a mismatch means the
    // header is never added and every request answers 401.
    const swPattern = /^\/api\/v1\/calls\/[0-9a-fA-F-]{36}\/audio$/
    expect(swPattern.test(callAudioPath(CALL_ID))).toBe(true)
  })
})

describe('filenameFrom', () => {
  it('prefers the UTF-8 form, so a name survives', () => {
    expect(
      filenameFrom("attachment; filename=\"call.ogg\"; filename*=UTF-8''Aziz_20260905-1403.ogg"),
    ).toBe('Aziz_20260905-1403.ogg')
  })

  it('decodes percent-escapes in the UTF-8 form', () => {
    expect(filenameFrom("attachment; filename*=UTF-8''Aziz%20Karimov.ogg")).toBe(
      'Aziz Karimov.ogg',
    )
  })

  it('falls back to the plain form, and then to a default', () => {
    expect(filenameFrom('attachment; filename="call_20260905.ogg"')).toBe('call_20260905.ogg')
    expect(filenameFrom(null)).toBe('call.ogg')
    expect(filenameFrom('attachment')).toBe('call.ogg')
  })

  it('does not throw on a malformed encoding from a rewriting proxy', () => {
    expect(filenameFrom("attachment; filename=\"safe.ogg\"; filename*=UTF-8''%E0%A4%A")).toBe(
      'safe.ogg',
    )
  })
})
