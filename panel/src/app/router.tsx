/**
 * The route table. Every page of SPEC §5.2, registered once.
 *
 * ═══ RBAC ═══════════════════════════════════════════════════════════════
 * This file is the FIRST of the two frontend permission checks
 * (CONVENTIONS.md §11, SPEC §5.1); the second is `NAV[].anyOf` in
 * `shared/layout/AppShell.tsx`. **Both are required.** The nav filter exists so
 * people are not shown doors they cannot open; the gate exists so a bookmark or
 * a pasted URL does not render a page the user has no business seeing. Neither
 * is security — the server check is the only one that decides anything, and a
 * gated page whose API call returns 403 is still the correct outcome.
 *
 * A user who reaches a route they lack the permission for is sent to `/`
 * (SPEC §5.1), not shown a 403 screen: the panel does not confirm that a page
 * exists to somebody who may not use it, for the same reason the server answers
 * 404 rather than 403 for a row owned by somebody else.
 * ════════════════════════════════════════════════════════════════════════
 *
 * `ROUTES` is exported as data so `nav.parity.test.ts` can assert that every
 * permission which shows a menu entry also opens that entry's gate. That test
 * is what stops the two lists drifting apart.
 *
 * Phase 5 tasks replace page BODIES. Nobody edits this table again until the
 * wiring phase (T103) — that is the whole point of T21.
 */
import { useEffect, type ReactElement } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import { LoginPage } from '@/modules/auth/LoginPage'
import { useAuth } from '@/modules/auth/store'
import { AgentDetailPage } from '@/modules/agents/AgentDetailPage'
import { AgentsPage } from '@/modules/agents/AgentsPage'
import { AlertsPage } from '@/modules/alerts/AlertsPage'
import { AnalysisDetailPage } from '@/modules/analysis/AnalysisDetailPage'
import { AnalysisListPage } from '@/modules/analysis/AnalysisListPage'
import { AnalysisQueuePage } from '@/modules/analysis/AnalysisQueuePage'
import { CallDetailPage } from '@/modules/calls/CallDetailPage'
import { CallsPage } from '@/modules/calls/CallsPage'
import { DashboardPage } from '@/modules/dashboard/DashboardPage'
import { LandingPage } from '@/modules/landing/LandingPage'
import { DeviceDetailPage } from '@/modules/devices/DeviceDetailPage'
import { DevicesPage } from '@/modules/devices/DevicesPage'
import { SettingsPage } from '@/modules/settings/SettingsPage'
import { UsersPage } from '@/modules/users/UsersPage'
import { landingPath } from '@/shared/auth/landing'
import { Perm, type Permission } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { AppShell, NotFoundNotice } from '@/shared/layout/AppShell'
import { Skeleton } from '@/shared/ui/primitives'

export interface RouteSpec {
  /** The URL pattern, exactly as SPEC §5.2 writes it. */
  path: string
  element: ReactElement
  /** The gate. Absent means "any authenticated user" (the dashboard only). */
  anyOf?: readonly Permission[]
  /** No token required at all. */
  isPublic?: boolean
  /** Rendered outside the AppShell: full screen, no sidebar. */
  fullScreen?: boolean
}

export const ROUTES: readonly RouteSpec[] = [
  // ── Public ────────────────────────────────────────────────────────────
  // The site's front page, and the only route here with no session at all.
  // It hands out the APK so somebody can install without an account — a
  // reinstall after a factory reset, a second handset, showing the product to
  // a visitor — none of which used to be possible without an admin issuing a
  // per-agent link first. It grants nothing: the app is inert until an
  // enrolment code is typed into it, and that is still an admin's decision.
  { path: '/', element: <LandingPage />, isPublic: true, fullScreen: true },
  { path: '/login', element: <LoginPage />, isPublic: true, fullScreen: true },
  //
  // `/i/:code` — the install landing page of SPEC §8.1 — is deliberately NOT
  // here. The SERVER answers it (`core/permissions.py::PUBLIC_ROUTES` already
  // lists `GET /i/{code}`) with server-rendered HTML. It is the first thing a
  // non-technical salesperson touches, on their own phone, over mobile data,
  // inside N40's 15 unaided minutes and against R17, the project's top
  // practical risk. Shipping a React bundle to that moment costs a download
  // before the first word appears and fails to a blank screen; a few KB of
  // HTML works without JS and serves the APK directly.

  // ── Authenticated, no permission of its own ───────────────────────────
  //
  // `/dashboard`, not `/`, since 2026-09-14: the root became the public front
  // page. `landingPath()` is what sends a signed-in user here and it is the
  // one place that knows the path — the post-login redirect and every gate
  // refusal both ask it rather than hard-coding an answer.
  { path: '/dashboard', element: <DashboardPage /> },

  // ── Operations ────────────────────────────────────────────────────────
  //
  // Removed 2026-09-05 at the client's request: `/enrolment`, `/numbers` and
  // the `/monitor` TV board. For a fifteen-person team, registering a work
  // number and issuing an enrolment code are things you do *to an agent*, so
  // they belong on the agent's own page rather than in two more top-level
  // sections. The capability is not gone — `AgentDetailPage` owns it.
  { path: '/calls', element: <CallsPage />, anyOf: [Perm.CALLS_READ, Perm.CALLS_READ_OWN] },
  { path: '/calls/:id', element: <CallDetailPage />, anyOf: [Perm.CALLS_READ, Perm.CALLS_READ_OWN] },
  { path: '/alerts', element: <AlertsPage />, anyOf: [Perm.ALERTS_READ] },
  {
    // Own-scope passes the gate and the SERVER narrows the query to the
    // caller's own installations — the house rule (CONVENTIONS.md §11), the
    // same shape `calls:read:own` already has. SPEC §5.2 gates this list on
    // `devices:read` alone, which left a `sales` user with a device detail
    // page and no way to reach it; the gate is widened and the narrowing lives
    // in `DeviceService.list()`, never in a second permission.
    path: '/devices',
    element: <DevicesPage />,
    anyOf: [Perm.DEVICES_READ, Perm.DEVICES_READ_OWN],
  },
  {
    path: '/devices/:installationId',
    element: <DeviceDetailPage />,
    anyOf: [Perm.DEVICES_READ, Perm.DEVICES_READ_OWN],
  },
  { path: '/agents', element: <AgentsPage />, anyOf: [Perm.AGENTS_READ] },
  { path: '/agents/:id', element: <AgentDetailPage />, anyOf: [Perm.AGENTS_READ] },

  // ── Analysis (SPEC-ANALYTICS §7.1) ────────────────────────────────────
  //
  // A SECTION OF ITS OWN, at the client's decision of 2026-09-17. Nothing
  // inside the existing pages changes: `/calls`, `/calls/:id` and `/dashboard`
  // keep working exactly as they do in production today, so a mistake in this
  // work cannot reach a screen the fleet already depends on. The cost is one
  // extra click from a call to its analysis, and a shortcut is a phase-2
  // decision with the client rather than a side effect of this task.
  //
  // All three gate on `analysis:read` and not on `analysis:run`: reading a
  // score is reviewing work, and a `manager` holds the first and not the
  // second (§6.1). The run button lives inside the pages and checks the second
  // for itself; the server refuses the POST either way.
  //
  // `/analysis/queue` is declared ABOVE `/analysis/:callId` for the reason the
  // server declares `/status` above `/calls/{call_id}`: the two do not collide
  // under react-router's ranked matching, but the literal path staying above
  // the parameterised one is the habit that keeps them from colliding the day
  // somebody renames a path.
  { path: '/analysis', element: <AnalysisListPage />, anyOf: [Perm.ANALYSIS_READ] },
  { path: '/analysis/queue', element: <AnalysisQueuePage />, anyOf: [Perm.ANALYSIS_READ] },
  { path: '/analysis/:callId', element: <AnalysisDetailPage />, anyOf: [Perm.ANALYSIS_READ] },

  // ── Administration ────────────────────────────────────────────────────
  { path: '/users', element: <UsersPage />, anyOf: [Perm.USERS_READ] },
  //
  // No `anyOf`: your own account is yours whatever your role. The section
  // inside it that resets OTHER people's passwords is gated on `users:write`
  // by the page, and by the server on every request it makes.
  { path: '/settings', element: <SettingsPage />, anyOf: undefined },
  //
  // Removed 2026-09-05 at the client's request: `/settings`. Recording is
  // continuous and unconditional — no setting has ever gated it — so a page of
  // thresholds was not something they wanted to be able to reach. The
  // `working_hours.*` values it exposed are still read by `modules/devices`
  // server-side, and only to decide when a silent phone is asleep rather than
  // broken; that is about when to raise an alert, never about when to record.
  //
  // `GET/PUT /api/v1/settings` deliberately keeps no caller but this page's
  // one read: retention behind an RBAC-protected API call is a better place
  // for it than a button, and better than editing a row in production by hand.
  //
  // The APK surface stays, because it is distribution and not configuration:
  // without it nobody can publish a build or raise the minimum version, and a
  // fleet of personal phones cannot be updated at all (N33).
]

function FullPageLoader() {
  return (
    <div className="grid min-h-screen place-items-center bg-bg" role="status" aria-live="polite">
      <Skeleton className="size-10 rounded-xl" />
      <span className="sr-only">{t('auth.checking')}</span>
    </div>
  )
}

/** A token is required. Remembers where the user was, so an expiry mid-session
 *  returns them to that page after logging back in. */
function Protected({ children }: { children: ReactElement }) {
  const status = useAuth((state) => state.status)
  const location = useLocation()

  if (status === 'idle' || status === 'loading') return <FullPageLoader />
  if (status === 'anonymous') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return children
}

/**
 * At least one of `anyOf`, or back to wherever this user belongs — which is the
 * dashboard for everybody except a `viewer`, whose dashboard would be five
 * tiles of 403 (see `shared/auth/landing.ts`).
 */
export function Gate({ anyOf, children }: { anyOf?: readonly Permission[]; children: ReactElement }) {
  const canAny = useAuth((state) => state.canAny)
  if (anyOf && !canAny(anyOf)) return <Navigate to={landingPath()} replace />
  return children
}

function guarded(route: RouteSpec): ReactElement {
  return <Gate anyOf={route.anyOf}>{route.element}</Gate>
}

export function AppRouter() {
  const status = useAuth((state) => state.status)
  const restore = useAuth((state) => state.restore)

  useEffect(() => {
    if (status === 'idle') void restore()
  }, [status, restore])

  const publicRoutes = ROUTES.filter((route) => route.isPublic)
  const fullScreenRoutes = ROUTES.filter((route) => !route.isPublic && route.fullScreen)
  const shellRoutes = ROUTES.filter((route) => !route.isPublic && !route.fullScreen)

  return (
    <Routes>
      {publicRoutes.map((route) => (
        <Route key={route.path} path={route.path} element={route.element} />
      ))}

      <Route
        element={
          <Protected>
            <Outlet />
          </Protected>
        }
      >
        {fullScreenRoutes.map((route) => (
          <Route key={route.path} path={route.path} element={guarded(route)} />
        ))}

        <Route element={<AppShell />}>
          {shellRoutes.map((route) => (
            <Route key={route.path} path={route.path} element={guarded(route)} />
          ))}
          <Route path="*" element={<NotFoundNotice />} />
        </Route>
      </Route>
    </Routes>
  )
}
