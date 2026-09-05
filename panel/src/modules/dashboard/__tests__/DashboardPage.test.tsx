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
import { render, screen } from '@testing-library/react'
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
  [Perm.CALLS_READ, 'dashboard.callsToday'],
  [Perm.CALLS_READ_OWN, 'dashboard.callsToday'],
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

function world() {
  fetchMock.mockImplementation((input) => {
    const url = String(input)
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

    await screen.findByText(t('dashboard.callsToday'))
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    // A number with no route is trivia (SPEC §5.2).
    expect(hrefs.some((href) => href?.startsWith('/calls'))).toBe(true)
    expect(hrefs).toContain('/devices')
    expect(hrefs).toContain('/alerts')
    expect(hrefs).toContain('/reports/gap')
  })

  it('asks the server for today only, in Asia/Tashkent', async () => {
    signIn([Perm.CALLS_READ])
    renderPage()

    await screen.findByText(t('dashboard.callsToday'))
    const url = String(fetchMock.mock.calls.find(([i]) => String(i).includes('/calls'))?.[0] ?? '')
    expect(url).toMatch(/date_from=\d{4}-\d{2}-\d{2}/)
    // Same day boundary as every other business date in the system (D-10).
    const from = /date_from=(\d{4}-\d{2}-\d{2})/.exec(url)?.[1]
    const to = /date_to=(\d{4}-\d{2}-\d{2})/.exec(url)?.[1]
    expect(from).toBe(to)
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
