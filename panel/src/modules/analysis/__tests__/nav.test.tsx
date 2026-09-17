/**
 * The TAHLIL section's two-place gate (CONVENTIONS.md §11, SPEC-ANALYTICS §7.1).
 *
 * `shared/layout/__tests__/nav.parity.test.ts` already asserts the general
 * invariant — every permission that makes a menu entry visible also opens that
 * route's gate — by walking both lists. This file asserts the SPECIFIC shape
 * §7.1 asked for, because the general test passes just as happily when the
 * section is missing from both lists at once:
 *
 *   · the group exists, with exactly the two entries §7.1 names;
 *   · all three routes are registered and all three gate on `analysis:read`;
 *   · `analysis:run` gates nothing at route level — it is a BUTTON permission,
 *     and a route gated on it would hide the score from the manager who is
 *     supposed to read it;
 *   · a `sales` user sees no menu entry and a pasted URL turns them away.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppRouter, ROUTES } from '@/app/router'
import { useAuth } from '@/modules/auth/store'
import { tokenStore } from '@/shared/api/client'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { NAV, visibleNav } from '@/shared/layout/AppShell'

const ANALYSIS_PATHS = ['/analysis', '/analysis/queue', '/analysis/:callId'] as const

const fetchMock = vi.fn<typeof fetch>()

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

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AppRouter />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The page's own <h1>. A nav link with the same words is not the page. */
function heading(name: string): HTMLElement | null {
  return screen.queryByRole('heading', { level: 1, name })
}

beforeEach(() => {
  fetchMock.mockReset()
  // Every analysis page fires a query the moment it mounts; an empty answer is
  // enough for a gate test and keeps the assertions about routing.
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ items: [], next_cursor: null, has_more: false, total: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  tokenStore.set('test-token')
})

afterEach(() => {
  vi.unstubAllGlobals()
  tokenStore.clear()
})

describe('the TAHLIL nav group', () => {
  it('carries exactly the two entries §7.1 names, in that order', () => {
    const group = NAV.filter((item) => item.group === 'nav.groupAnalysis')
    expect(group.map((item) => item.to)).toEqual(['/analysis', '/analysis/queue'])
    expect(group.map((item) => t(item.labelKey))).toEqual(['Baholashlar', 'Tahlil navbati'])
  })

  it('sits below MA\'MURIYAT', () => {
    const groups = NAV.map((item) => item.group)
    expect(groups.lastIndexOf('nav.groupAdmin')).toBeLessThan(
      groups.indexOf('nav.groupAnalysis'),
    )
  })

  it('gates both entries on analysis:read and never on analysis:run', () => {
    for (const item of NAV.filter((entry) => entry.group === 'nav.groupAnalysis')) {
      expect(item.anyOf).toEqual([Perm.ANALYSIS_READ])
    }
  })

  it('does not put the detail route in the menu — it is reached from the list', () => {
    expect(NAV.map((item) => item.to)).not.toContain('/analysis/:callId')
  })

  it('shows both entries to a holder of analysis:read', () => {
    const visible = visibleNav(new Set([Perm.ANALYSIS_READ])).map((item) => item.to)
    expect(visible).toContain('/analysis')
    expect(visible).toContain('/analysis/queue')
  })

  it('hides the whole section from a sales user', () => {
    // `sales` holds `calls:read:own`, `audio:play:own` and `devices:read:own`
    // and neither analysis permission — a decision, not an oversight (§12 Q1).
    const visible = visibleNav(
      new Set([Perm.CALLS_READ_OWN, Perm.AUDIO_PLAY_OWN, Perm.DEVICES_READ_OWN]),
    ).map((item) => item.to)
    expect(visible).not.toContain('/analysis')
    expect(visible).not.toContain('/analysis/queue')
  })
})

describe('the routes behind it', () => {
  it('registers all three, each gated on analysis:read', () => {
    for (const path of ANALYSIS_PATHS) {
      const route = ROUTES.find((entry) => entry.path === path)
      expect(route, `route ${path} is not registered`).toBeDefined()
      expect(route?.anyOf).toEqual([Perm.ANALYSIS_READ])
    }
  })

  it('points every TAHLIL menu entry at a registered route', () => {
    const paths = new Set(ROUTES.map((route) => route.path))
    for (const item of NAV.filter((entry) => entry.group === 'nav.groupAnalysis')) {
      expect(paths.has(item.to), `${item.to} has no route`).toBe(true)
    }
  })

  it('renders the list for a manager', () => {
    signIn([Perm.ANALYSIS_READ])
    renderAt('/analysis')
    expect(heading(t('page.analysis'))).not.toBeNull()
  })

  it('renders the queue for a manager', () => {
    signIn([Perm.ANALYSIS_READ])
    renderAt('/analysis/queue')
    // The literal path wins over `/analysis/:callId`; a queue rendered as a
    // call id would 404 against the server for ever.
    expect(heading(t('page.analysisQueue'))).not.toBeNull()
    expect(heading(t('page.analysisDetail'))).toBeNull()
  })

  it('sends a sales user back to the dashboard from every analysis URL', () => {
    signIn([Perm.CALLS_READ_OWN, Perm.AUDIO_PLAY_OWN, Perm.DEVICES_READ_OWN])

    for (const path of ['/analysis', '/analysis/queue', '/analysis/some-call-id']) {
      const view = renderAt(path)
      expect(heading(t('page.dashboard')), `${path} rendered for a sales user`).not.toBeNull()
      expect(heading(t('page.analysis'))).toBeNull()
      expect(heading(t('page.analysisQueue'))).toBeNull()
      expect(heading(t('page.analysisDetail'))).toBeNull()
      view.unmount()
    }
  })
})
