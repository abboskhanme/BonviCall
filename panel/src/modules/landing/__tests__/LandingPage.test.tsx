/**
 * The public front page.
 *
 * What is pinned is the boundary, not the layout: this page is reachable with
 * no session and hands out a binary, so the tests are about what it asks for,
 * what it offers, and what it must never require.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LandingPage } from '@/modules/landing/LandingPage'
import { preferredVariant } from '@/modules/landing/variant'
import { useAuth } from '@/modules/auth/store'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

const fetchMock = vi.fn<typeof fetch>()

function release(variant: 'legacy28' | 'modern34', versionCode: number) {
  return {
    version: '1.0.7',
    version_code: versionCode,
    variant,
    size_bytes: 2_630_857,
    apk_sha256: 'f'.repeat(64),
    min_api_level: 26,
    release_notes_uz: null,
    published_at: '2026-09-14T09:00:00+05:00',
  }
}

function world(items: unknown[], status = 200) {
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ items, total: items.length }), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
  return () => String(fetchMock.mock.calls.at(-1)?.[0] ?? '')
}

function lastInit(): RequestInit {
  return (fetchMock.mock.calls.at(-1)?.[1] ?? {}) as RequestInit
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LandingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.clear()
  useAuth.setState({ status: 'anonymous', user: null, permissions: new Set(), loginError: null })
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('what it needs', () => {
  it('asks the server for the build without sending a token', async () => {
    const lastUrl = world([release('legacy28', 8)])
    renderPage()

    await screen.findByText(t('landing.variantLegacy'))

    expect(lastUrl()).toContain('/app/latest')
    const headers = new Headers(lastInit().headers)
    expect(headers.has('Authorization')).toBe(false)
  })

  it('offers a way in, for somebody who has an account', () => {
    world([])
    renderPage()

    expect(screen.getByRole('link', { name: t('landing.signIn') })).toHaveAttribute(
      'href',
      '/login',
    )
  })

  it('sends a signed-in reader to the panel instead of to the login form', () => {
    /** Offering "Kirish" to somebody who is already signed in walks them into
     *  a page that bounces them straight back here. */
    world([])
    useAuth.setState({ status: 'authenticated' })
    renderPage()

    expect(screen.queryByRole('link', { name: t('landing.signIn') })).toBeNull()
    expect(screen.getByRole('link', { name: t('landing.openPanel') })).toHaveAttribute(
      'href',
      '/dashboard',
    )
  })
})

describe('what it offers', () => {
  it('links the download straight at the public download path', async () => {
    world([release('legacy28', 8)])
    renderPage()

    const link = await screen.findByRole('link', { name: t('landing.download') })
    // An anchor, not a fetch: a 30 MB stream with a Content-Disposition is the
    // browser's own downloader's job.
    //
    // And it names the VARIANT. Both flavours of one release carry the same
    // version code, so the code alone named two files and the server handed
    // back whichever it found first — this card could offer the other build.
    expect(link).toHaveAttribute('href', '/api/v1/app/download/8?variant=legacy28')
  })

  it('offers each card its OWN variant, not whichever the server picks', async () => {
    world([release('legacy28', 8), release('modern34', 8)])
    renderPage()

    const links = await screen.findAllByRole('link', { name: t('landing.download') })
    const hrefs = links.map((link) => link.getAttribute('href'))
    expect(hrefs).toContain('/api/v1/app/download/8?variant=legacy28')
    expect(hrefs).toContain('/api/v1/app/download/8?variant=modern34')
  })

  it('names the version and the size, so a phone on mobile data knows', async () => {
    world([release('legacy28', 8)])
    renderPage()

    expect(
      await screen.findByText(t('landing.versionLine', { version: '1.0.7', size: '2.5' })),
    ).toBeInTheDocument()
  })

  it('offers both flavours when both are published', async () => {
    world([release('legacy28', 8), release('modern34', 9)])
    renderPage()

    await screen.findByText(t('landing.variantLegacy'))
    expect(screen.getByText(t('landing.variantModern'))).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: t('landing.download') })).toHaveLength(2)
  })

  it('says so plainly when nothing has been published yet', async () => {
    /** The ordinary state of a fresh server. It must not read as a fault, and
     *  it must not be a button that goes nowhere. */
    world([])
    renderPage()

    await waitFor(() =>
      expect(screen.getByText(t('landing.noBuildTitle'))).toBeInTheDocument(),
    )
    expect(screen.queryByRole('link', { name: t('landing.download') })).toBeNull()
  })

  it('separates a broken server from an empty one', async () => {
    world([], 500)
    renderPage()

    await waitFor(() =>
      expect(screen.getByText(t('landing.loadFailed'))).toBeInTheDocument(),
    )
    expect(screen.queryByText(t('landing.noBuildTitle'))).toBeNull()
  })
})

describe('choosing a build for the reader', () => {
  /** Rough on purpose: a wrong guess costs a tap on the other card, and both
   *  are always offered. */
  it('sends Android 13 and above to the modern flavour', () => {
    expect(preferredVariant('Mozilla/5.0 (Linux; Android 14; Pixel 8)')).toBe('modern34')
    expect(preferredVariant('Mozilla/5.0 (Linux; Android 13; SM-G991B)')).toBe('modern34')
  })

  it('sends everything older to the one the fleet actually runs', () => {
    expect(preferredVariant('Mozilla/5.0 (Linux; Android 12; Redmi Note 12)')).toBe('legacy28')
    expect(preferredVariant('Mozilla/5.0 (Linux; Android 9; SM-J600F)')).toBe('legacy28')
  })

  it('falls back rather than guessing when it cannot tell', () => {
    // A desktop browser, which is where an admin looks at this page.
    expect(preferredVariant('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe(
      'legacy28',
    )
    expect(preferredVariant('')).toBe('legacy28')
  })
})
