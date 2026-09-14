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
    renderAt('/users')

    // The page title is the <h1>; the sidebar carries the same words as a
    // link, so the heading role is what distinguishes "rendered" from
    // "merely listed in a menu".
    expect(heading(t('page.users'))).toBeNull()
    // Redirected to the dashboard, per SPEC §5.1.
    expect(heading(t('page.dashboard'))).not.toBeNull()
  })

  it('renders the same page once the permission is held', () => {
    signIn([Perm.USERS_READ])
    renderAt('/users')

    expect(heading(t('page.users'))).not.toBeNull()
  })

  it('sends an anonymous visitor to /login and remembers the page', () => {
    renderAt('/calls')

    expect(screen.getByText(t('auth.loginTitle'))).toBeInTheDocument()
    expect(heading(t('page.calls'))).toBeNull()
  })

  it('has no route for the sections the client removed', () => {
    // Removed 2026-09-05: the TV board, the work-numbers page and the
    // enrolment funnel. Registering a number and issuing an enrolment code are
    // things you do to an agent, so they live on the agent's page instead; the
    // board had no audience. Asserted rather than merely deleted, because a
    // dead route is easy to reintroduce by copying a neighbouring one.
    const paths = ROUTES.map((route) => route.path)
    expect(paths).not.toContain('/monitor')
    expect(paths).not.toContain('/numbers')
    expect(paths).not.toContain('/enrolment')
  })

  it('keeps the dashboard as the fallback for everybody who has a tile on it', () => {
    signIn([Perm.CALLS_READ])
    renderAt('/users')

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

  it('does not register the routes the client asked us to remove', () => {
    // `/monitor`, `/numbers` and `/enrolment` went on 2026-09-05; `/settings`
    // followed, because recording is continuous and unconditional and a page
    // of thresholds was not something they wanted to reach. A deleted route is
    // easy to reintroduce by copying a neighbouring one, so it is asserted
    // rather than remembered.
    const paths = ROUTES.map((route) => route.path)
    // NOTE: `/settings` is back since 2026-09-14, as the profile page. What
    // was removed in 2026-09-05 was a page of recording thresholds, and the
    // path was free.
    expect(paths).not.toContain('/monitor')
    expect(paths).not.toContain('/numbers')
    expect(paths).not.toContain('/enrolment')
    // `/settings/app-versions` and `/audit` went on 2026-09-14, also at the
    // client's request. The APK surface is gone from the PANEL only: the
    // server still publishes builds, the enrolment link still serves one, and
    // the phone still asks whether it must update — none of which the panel
    // was doing.
    expect(paths).not.toContain('/settings/app-versions')
    expect(paths).not.toContain('/audit')
    // `/reports/gap` followed on 2026-09-14. The number it led with is still
    // on the dashboard; the drill-down page is not.
    expect(paths).not.toContain('/reports/gap')
  })

  it('does not register /i/:code — the server renders the install page', () => {
    // SPEC §8.1 is answered by the server as plain HTML: it is the first thing
    // a salesperson touches on their own phone inside N40's 15 unaided
    // minutes, and a React bundle there fails to a blank screen.
    expect(ROUTES.map((route) => route.path)).not.toContain('/i/:code')
  })

  it('keeps a sales user out of every oversight surface', () => {
    // `sales` holds exactly `calls:read:own`, `audio:play:own` and
    // `devices:read:own` — verified against the live server. The oversight
    // pages answer 403 for them, and the gate must not let a pasted URL
    // render a page whose every request will fail.
    signIn([Perm.CALLS_READ_OWN, Perm.AUDIO_PLAY_OWN, Perm.DEVICES_READ_OWN])

    for (const path of [
      '/alerts',
      '/agents',
      '/users',
    ]) {
      const view = renderAt(path)
      expect(heading(t('page.dashboard'))).not.toBeNull()
      view.unmount()
    }
  })

  it('lets a sales user open their own calls, which the server then narrows', () => {
    // Own-scope passes the gate; `CallService.list()` filters the rows. The
    // panel must not re-implement that rule (CONVENTIONS.md §11).
    signIn([Perm.CALLS_READ_OWN])
    renderAt('/calls')

    expect(heading(t('page.calls'))).not.toBeNull()
  })

  it('gates every non-public route except the dashboard', () => {
    // The dashboard is "any authenticated user" (SPEC §5.2) and the two public
    // pages carry no gate by definition. `/settings` joined them on
    // 2026-09-14: your own account is yours whatever your role, and the one
    // section on it that touches OTHER accounts is gated inside the page and
    // by the server on every request it makes.
    //
    // The exceptions are listed rather than pattern-matched, so a page added
    // later still cannot ship ungated by accident.
    const ANY_AUTHENTICATED = ['/', '/settings']
    const ungated = ROUTES.filter(
      (route) =>
        !route.isPublic && !ANY_AUTHENTICATED.includes(route.path) && !route.anyOf?.length,
    )
    expect(ungated.map((route) => route.path)).toEqual([])
  })
})
