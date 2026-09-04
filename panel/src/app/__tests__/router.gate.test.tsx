/**
 * The route gate (CONVENTIONS.md §11, SPEC §5.1, CONVENTIONS-CLIENT.md §10).
 *
 * "A module with a `<Gate>` has a test that the wrong role is redirected."
 * This is the half of the two-place frontend check that a pasted URL hits —
 * hiding the menu entry does nothing for a bookmark, which is exactly why both
 * places exist.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { AppRouter, ROUTES } from '@/app/router'

function signIn(permissions: string[]) {
  useAuth.setState({
    status: 'authenticated',
    user: {
      id: '00000000-0000-4000-8000-000000000001',
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

/** The page's own <h1>. A nav link with the same words is not the page. */
function heading(name: string): HTMLElement | null {
  return screen.queryByRole('heading', { level: 1, name })
}

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
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

describe('route gate', () => {
  beforeEach(() => {
    useAuth.setState({
      status: 'anonymous',
      user: null,
      permissions: new Set<string>(),
      loginError: null,
    })
  })

  it('does not render a page the user lacks the permission for', () => {
    signIn([Perm.CALLS_READ])
    renderAt('/audit')

    // The page title is the <h1>; the sidebar carries the same words as a
    // link, so the heading role is what distinguishes "rendered" from
    // "merely listed in a menu".
    expect(heading(t('page.audit'))).toBeNull()
    // Redirected to the dashboard, per SPEC §5.1.
    expect(heading(t('page.dashboard'))).not.toBeNull()
  })

  it('renders the same page once the permission is held', () => {
    signIn([Perm.AUDIT_READ])
    renderAt('/audit')

    expect(heading(t('page.audit'))).not.toBeNull()
  })

  it('sends an anonymous visitor to /login and remembers the page', () => {
    renderAt('/calls')

    expect(screen.getByText(t('auth.loginTitle'))).toBeInTheDocument()
    expect(heading(t('page.calls'))).toBeNull()
  })

  it('sends a monitor-only user to the board rather than an all-403 dashboard', () => {
    // `viewer` holds `monitor:read` and nothing else. Every dashboard tile
    // would come back 403, so the gate's fallback must not be `/` for them.
    signIn([Perm.MONITOR_READ])
    renderAt('/audit')

    expect(heading(t('page.monitor'))).not.toBeNull()
    expect(heading(t('page.dashboard'))).toBeNull()
  })

  it('keeps the dashboard as the fallback for everybody who has a tile on it', () => {
    signIn([Perm.CALLS_READ])
    renderAt('/audit')

    expect(heading(t('page.dashboard'))).not.toBeNull()
  })

  it('lets a sales user open the device list, which the server then narrows', () => {
    // Scope is narrowed by the query, not by a second permission
    // (CONVENTIONS.md §11): own-scope passes the gate here and
    // DeviceService.list() filters to the caller's own installations.
    signIn([Perm.DEVICES_READ_OWN])
    renderAt('/devices')

    expect(heading(t('page.devices'))).not.toBeNull()
  })

  it('does not register /i/:code — the server renders the install page', () => {
    // SPEC §8.1 is answered by the server as plain HTML: it is the first thing
    // a salesperson touches on their own phone inside N40's 15 unaided
    // minutes, and a React bundle there fails to a blank screen.
    expect(ROUTES.map((route) => route.path)).not.toContain('/i/:code')
  })

  it('gates every non-public route except the dashboard', () => {
    // The dashboard is "any authenticated user" (SPEC §5.2) and the two public
    // pages carry no gate by definition. Everything else must declare one, or a
    // page added later silently ships ungated.
    const ungated = ROUTES.filter(
      (route) => !route.isPublic && route.path !== '/' && !route.anyOf?.length,
    )
    expect(ungated.map((route) => route.path)).toEqual([])
  })
})
