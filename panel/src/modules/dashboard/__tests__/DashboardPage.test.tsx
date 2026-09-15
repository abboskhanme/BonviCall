/**
 * The dashboard, and the invariant underneath it.
 *
 * `DASHBOARD_PERMISSIONS` decides where a user LANDS after logging in. If this
 * page renders a tile whose permission is missing from that list, a role can
 * exist that is sent here and greeted by a 403 — on the one page they cannot
 * navigate away from a mistake on. So the two lists are asserted against each
 * other in both directions, not just spot-checked.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DashboardPage } from '@/modules/dashboard/DashboardPage'
import { useAuth } from '@/modules/auth/store'
import { DASHBOARD_PERMISSIONS } from '@/shared/auth/landing'
import { Perm, type Permission } from '@/shared/auth/permissions'
import { tokenStore } from '@/shared/api/client'
import { t } from '@/shared/i18n'

/**
 * Every permission that makes a tile appear, paired with the tile's label.
 * Kept beside the page rather than inside it so the assertion below is a
 * genuine cross-check and not the page agreeing with itself.
 */
const TILE_PERMISSIONS: ReadonlyArray<[Permission, string]> = [
  [Perm.CALLS_READ, 'dashboard.callsInPeriod'],
  [Perm.CALLS_READ_OWN, 'dashboard.callsInPeriod'],
  [Perm.DEVICES_READ, 'dashboard.devicesNeedingAttention'],
  [Perm.DEVICES_READ_OWN, 'dashboard.devicesNeedingAttention'],
  [Perm.ALERTS_READ, 'dashboard.openAlerts'],
  [Perm.REPORTS_READ, 'dashboard.captureRate'],
]

const fetchMock = vi.fn<typeof fetch>()

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** One well-formed `/calls/stats` window: three daily buckets, one call each. */
function stats(period = 'week') {
  const buckets = ['2026-09-13', '2026-09-14', '2026-09-15'].map((day) => ({
    date_from: day,
    date_to: day,
    incoming_answered: 1,
    outgoing_answered: 0,
    missed: 0,
    rejected: 0,
    no_answer: 0,
    total: 1,
  }))
  return {
    period,
    granularity: 'day',
    date_from: '2026-09-13',
    date_to: '2026-09-15',
    buckets,
  }
}

function world() {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
    // Before the list branch: `/calls/stats` starts with `/calls`, and the two
    // shapes are nothing alike.
    if (url.includes('/api/v1/calls/stats')) {
      const period = new URL(url, 'http://localhost').searchParams.get('period') ?? 'week'
      return Promise.resolve(jsonResponse(stats(period)))
    }
    if (url.includes('/api/v1/calls')) {
      return Promise.resolve(jsonResponse({ items: [], next_cursor: null, has_more: false, total: 7 }))
    }
    if (url.includes('/api/v1/devices')) return Promise.resolve(jsonResponse({ items: [], total: 0 }))
    if (url.includes('/api/v1/alerts')) return Promise.resolve(jsonResponse({ items: [], total: 0 }))
    if (url.includes('/api/v1/reports/gap')) {
      return Promise.resolve(
        jsonResponse({
          answered_calls: 10,
          calls_with_audio: 8,
          missing_total: 2,
          capture_rate: '80.00',
          by_reason: [],
          by_model: [],
          by_agent: [],
          open_deltas: [],
        }),
      )
    }
    return Promise.resolve(jsonResponse({}))
  })
}

function signIn(permissions: readonly string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: 'user-1',
      email: 'admin@bonvi.uz',
      full_name: 'Administrator',
      role: 'admin',
      permissions: [...permissions],
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
  world()
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('the landing-page invariant', () => {
  it('renders no tile whose permission is outside DASHBOARD_PERMISSIONS', () => {
    const declared = new Set<string>(DASHBOARD_PERMISSIONS)
    const rendered = TILE_PERMISSIONS.map(([permission]) => permission)
    const stray = rendered.filter((permission) => !declared.has(permission))
    // A stray tile means some role lands here and is met by a 403.
    expect(stray).toEqual([])
  })

  it('has a tile for every permission DASHBOARD_PERMISSIONS claims', () => {
    const rendered = new Set<string>(TILE_PERMISSIONS.map(([permission]) => permission))
    const unused = DASHBOARD_PERMISSIONS.filter((permission) => !rendered.has(permission))
    // The other direction matters too: a permission listed but not rendered
    // sends a user here to an empty page and calls it their landing page.
    expect(unused).toEqual([])
  })

  it('shows each tile to a user holding only its own permission', async () => {
    for (const [permission, labelKey] of TILE_PERMISSIONS) {
      signIn([permission])
      const view = renderPage()
      expect(
        await screen.findByText(t(labelKey as Parameters<typeof t>[0])),
      ).toBeInTheDocument()
      view.unmount()
    }
  })
})

describe('tiles', () => {
  it('links every tile to the page that explains it', async () => {
    signIn(DASHBOARD_PERMISSIONS)
    const { container } = renderPage()

    await screen.findByText(t('dashboard.callsInPeriod'))
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    // A number with no route is trivia (SPEC §5.2).
    expect(hrefs.some((href) => href?.startsWith('/calls'))).toBe(true)
    expect(hrefs).toContain('/devices')
    expect(hrefs).toContain('/alerts')
    expect(hrefs.some((href) => href?.startsWith('/calls?has_audio=false'))).toBe(true)
  })

  /**
   * The window is the server's arithmetic, and the page must not do its own:
   * a browser working out "a week ago" does it in ITS timezone, and every
   * business date here is an Asia/Tashkent calendar date (D-10).
   */
  it('asks for a named period and takes the dates from the answer', async () => {
    signIn([Perm.CALLS_READ])
    renderPage()

    await screen.findByText(t('dashboard.callsInPeriod'))
    const url = String(
      fetchMock.mock.calls.find(([i]) => String(i).includes('/calls/stats'))?.[0] ?? '',
    )
    expect(url).toContain('period=week')
    expect(url).not.toMatch(/date_from=/)
    // …and the tile links to the window the server named, not to one it made up.
    await waitFor(() => {
      const link = [...document.querySelectorAll('a')]
        .map((a) => a.getAttribute('href'))
        .find((href) => href?.startsWith('/calls?date_from='))
      expect(link).toBe('/calls?date_from=2026-09-13&date_to=2026-09-15')
    })
  })

  it('says so plainly when a role has nothing to show', () => {
    // Unreachable today, but the alternative is an empty page that looks broken.
    signIn([Perm.AUDIT_READ])
    renderPage()
    expect(screen.getByText(t('dashboard.nothingToShow'))).toBeInTheDocument()
  })

  it('renders a dash rather than a zero while a figure is still loading', () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    signIn([Perm.CALLS_READ])
    renderPage()
    // "0 calls today" and "we do not know yet" are different claims, and the
    // first one is alarming.
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
