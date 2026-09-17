/**
 * The shell: sidebar on a desktop, a drawer on a narrow screen, both driven by
 * the SAME `NAV` array so a menu entry cannot exist in one and not the other.
 *
 * ═══ RBAC ═══════════════════════════════════════════════════════════════
 * This file is the SECOND of the two frontend permission checks
 * (CONVENTIONS.md §11, SPEC §5.1). The first is `<Gate anyOf>` in
 * `app/router.tsx`. **Both are required and neither replaces the other:**
 *
 *   • hiding a menu item is NOT access control — a pasted URL opens the page
 *     without ever touching this file;
 *   • the gate without the nav filter shows people doors they cannot open.
 *
 * Neither is security. The server check is the only one that decides anything.
 *
 * `nav.parity.test.ts` asserts that every permission which makes an item
 * visible here also opens that route's gate, so the two lists cannot drift.
 * ════════════════════════════════════════════════════════════════════════
 */
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BellRing,
  BookUser,
  ChevronsLeft,
  ChevronsRight,
  ClipboardCheck,
  Contact,
  LayoutDashboard,
  ListChecks,
  Menu,
  MessagesSquare,
  Phone,
  Smartphone,
  Sparkles,
  Star,
  UserCog,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { ChangePasswordModal } from '@/modules/auth/ChangePasswordModal'
import { AccountMenu } from './AccountMenu'
import { useAuth } from '@/modules/auth/store'
import { Perm, type Permission } from '@/shared/auth/permissions'
import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { Button } from '@/shared/ui/primitives'

type IconComponent = typeof LayoutDashboard

export interface NavItem {
  /** Must match a path in `ROUTES` (app/router.tsx). Asserted by a test. */
  to: string
  labelKey: MessageKey
  icon: IconComponent
  /**
   * Show the item when the user holds AT LEAST ONE of these. Absent means
   * "any authenticated user", which is true of the dashboard only.
   */
  anyOf?: readonly Permission[]
  /** Section heading above the item. Repeated headings collapse into one. */
  group?: MessageKey
}

/**
 * The finished menu (T103). Detail routes (`/agents/:id`, `/calls/:id`,
 * `/devices/:installationId`) are reached from their list and are deliberately
 * absent; `/login` and `/i/:code` are outside the shell.
 *
 * ═══ Ordering ═══════════════════════════════════════════════════════════
 * Within **Kundalik ish** the order is what somebody opens the panel to do,
 * most often first:
 *
 *   Calls    the product. The reason anybody logs in.
 *   Alerts   the to-do list — the only page that tells you something needs
 *            doing rather than waiting to be asked. Second because a fault
 *            nobody looks for is a fault nobody fixes.
 *   Devices  fleet health, read when an alert points here or weekly.
 *   Agents   the rollout. Heavy for a few weeks, then rare — so it sorts
 *            last despite being where enrolment lives.
 *
 * Reports are weekly, administration is occasional, and both keep their own
 * groups so the daily four are never more than four.
 *
 * ═══ RBAC ═══════════════════════════════════════════════════════════════
 * **Hiding a menu item is not access control**, and this is the file where
 * that is easiest to forget, because it is the file where visibility is
 * decided. `<Gate anyOf>` in `app/router.tsx` still guards every route, the
 * server still guards every request, and `nav.parity.test.ts` still asserts
 * that a permission which shows an entry also opens its gate.
 * ════════════════════════════════════════════════════════════════════════
 */
export const NAV: readonly NavItem[] = [
  { to: '/dashboard', labelKey: 'nav.dashboard', icon: LayoutDashboard },

  {
    to: '/calls',
    labelKey: 'nav.calls',
    icon: Phone,
    anyOf: [Perm.CALLS_READ, Perm.CALLS_READ_OWN],
    group: 'nav.groupOperations',
  },
  {
    // Directly after Qo'ng'iroqlar, because it answers the question the list
    // raises: the list says what happened, this says whether anybody was left
    // waiting. Same permissions as the list — a salesperson sees their own row
    // and the server narrows the query, which is why it is here in Kundalik ish
    // and not in Tahlil.
    to: '/activity',
    labelKey: 'nav.activity',
    icon: Activity,
    anyOf: [Perm.CALLS_READ, Perm.CALLS_READ_OWN],
    group: 'nav.groupOperations',
  },
  {
    // The same calls again, grouped by the person on the other end. Third
    // because it answers the question the first two raise — "who is this
    // number?" — and `/clients/:key` is deliberately absent, like every other
    // detail route: it opens from a row.
    to: '/clients',
    labelKey: 'nav.clients',
    icon: Contact,
    anyOf: [Perm.CALLS_READ, Perm.CALLS_READ_OWN],
    group: 'nav.groupOperations',
  },
  {
    to: '/alerts',
    labelKey: 'nav.alerts',
    icon: BellRing,
    anyOf: [Perm.ALERTS_READ],
    group: 'nav.groupOperations',
  },
  {
    // **`devices:read:own` only, since 2026-09-13**, and the narrowing is the
    // whole point: that permission belongs to `sales` and to nobody else
    // (`core/permissions.py`), so this entry is now a salesperson's one-row
    // view of their own handset — "is it still reporting?" — and disappears
    // for an admin or a manager, who read the same health as columns on
    // Xodimlar. One menu entry for the fleet, not two, which is what the
    // client asked for; the page and the route are untouched, and every link
    // into `/devices/:installationId` from Ogohlantirishlar still works.
    to: '/devices',
    labelKey: 'nav.devices',
    icon: Smartphone,
    anyOf: [Perm.DEVICES_READ_OWN],
    group: 'nav.groupOperations',
  },
  {
    // Where the rollout lives since `/enrolment` and `/numbers` were removed:
    // issuing a code, assigning a work number and reading the funnel are all
    // on the agent's own card now.
    to: '/agents',
    labelKey: 'nav.agents',
    icon: Users,
    anyOf: [Perm.AGENTS_READ],
    group: 'nav.groupOperations',
  },

  {
    to: '/users',
    labelKey: 'nav.users',
    icon: UserCog,
    anyOf: [Perm.USERS_READ],
    group: 'nav.groupAdmin',
  },
  {
    // Reference data, not a report: editing this list changes the names on
    // every other screen, which is why it gates on settings rather than on
    // calls and why it lives in MA'MURIYAT.
    to: '/contacts',
    labelKey: 'nav.contacts',
    icon: BookUser,
    anyOf: [Perm.SETTINGS_READ],
    group: 'nav.groupAdmin',
  },
  {
    to: '/groups',
    labelKey: 'nav.groups',
    icon: MessagesSquare,
    anyOf: [Perm.GROUPS_READ],
    group: 'nav.groupAdmin',
  },

  // ── TAHLIL (SPEC-ANALYTICS §7.1) ──────────────────────────────────────
  //
  // Its own group, below MA'MURIYAT, at the client's decision of 2026-09-17:
  // the analysis is a separate section and nothing inside the existing pages
  // changes. Two entries, because reading a score and asking why nothing has
  // been scored are two different jobs — the second is the one an admin opens
  // when the queue goes quiet, and without it that question has no answer
  // short of the database (§7.5).
  //
  // `/analysis/:callId` is deliberately absent, like every other detail route:
  // it is reached from its list.
  //
  // Both gate on `analysis:read`, which `admin` and `manager` hold and `sales`
  // does not (§6.1) — so a salesperson sees no group at all here, and the route
  // gate in `app/router.tsx` turns a pasted URL away as well.
  {
    // First in the group: the overview is what somebody opens the section to
    // see. The three below it answer "which call?", "why is nothing scored?"
    // and "scored against what?" — each of them a follow-up to a number here.
    to: '/analytics',
    labelKey: 'nav.analytics',
    icon: BarChart3,
    anyOf: [Perm.ANALYSIS_READ],
    group: 'nav.groupAnalysis',
  },
  {
    to: '/analysis',
    labelKey: 'nav.analysis',
    icon: Sparkles,
    anyOf: [Perm.ANALYSIS_READ],
    group: 'nav.groupAnalysis',
  },
  {
    to: '/analysis/queue',
    labelKey: 'nav.analysisQueue',
    icon: ListChecks,
    anyOf: [Perm.ANALYSIS_READ],
    group: 'nav.groupAnalysis',
  },
  {
    // Last, and visible to every reader of a score rather than only to the
    // admin who may change it: a score is not reviewable without the criteria
    // it was given against. The editing controls inside check `settings:write`
    // for themselves.
    to: '/rubric',
    labelKey: 'nav.rubric',
    icon: ClipboardCheck,
    anyOf: [Perm.ANALYSIS_READ],
    group: 'nav.groupAnalysis',
  },
  {
    // The only entry in this group a salesperson can see, and the only page in
    // the product that shows them a judgement of their own work — because it is
    // the customer's judgement and not the machine's.
    to: '/surveys',
    labelKey: 'nav.surveys',
    icon: Star,
    anyOf: [Perm.SURVEYS_READ, Perm.SURVEYS_READ_OWN],
    group: 'nav.groupAnalysis',
  },
]

/** The items this permission set may see. Pure, so the parity test can use it. */
export function visibleNav(
  held: ReadonlySet<string>,
  nav: readonly NavItem[] = NAV,
): NavItem[] {
  return nav.filter((item) => !item.anyOf || item.anyOf.some((perm) => held.has(perm)))
}

/**
 * Whether this entry highlights only on an exact match.
 *
 * A parent entry normally stays lit on its detail pages — `/calls` while
 * reading `/calls/:id` is correct and is what people expect. It stops being
 * correct when ANOTHER menu entry lives underneath it: on `/analysis/queue`
 * both "Baholashlar" and "Tahlil navbati" would light up, and two active items
 * is the menu failing to answer "which page am I on". Derived from NAV rather
 * than flagged per item, so adding a nested entry later cannot forget it.
 *
 * `/dashboard` keeps its own exact match: it is the fallback every gate
 * refusal lands on, and it has no children to inherit the rule from.
 */
function matchesExactly(item: NavItem, nav: readonly NavItem[]): boolean {
  if (item.to === '/dashboard') return true
  return nav.some((other) => other.to.startsWith(`${item.to}/`))
}

function NavList({
  items,
  collapsed,
  onNavigate,
}: {
  items: readonly NavItem[]
  collapsed: boolean
  onNavigate?: () => void
}) {
  let lastGroup: MessageKey | undefined
  return (
    <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2" aria-label={t('nav.menu')}>
      {items.map((item) => {
        const showGroup = !collapsed && item.group !== undefined && item.group !== lastGroup
        lastGroup = item.group
        const Icon = item.icon
        return (
          <div key={item.to}>
            {showGroup && item.group ? (
              <p className="px-3 pb-1 pt-4 text-2xs font-semibold uppercase tracking-wide text-muted">
                {t(item.group)}
              </p>
            ) : null}
            <NavLink
              to={item.to}
              end={matchesExactly(item, NAV)}
              onClick={onNavigate}
              title={collapsed ? t(item.labelKey) : undefined}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  collapsed && 'justify-center px-2',
                  isActive
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-muted hover:bg-surface-2 hover:text-text',
                )
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              {collapsed ? null : <span className="truncate">{t(item.labelKey)}</span>}
            </NavLink>
          </div>
        )
      })}
    </nav>
  )
}

function Sidebar({
  collapsed,
  onToggleCollapsed,
  items,
  onNavigate,
}: {
  collapsed: boolean
  onToggleCollapsed?: () => void
  items: readonly NavItem[]
  onNavigate?: () => void
}) {
  return (
    <div className="flex h-full flex-col border-e border-border bg-surface">
      <div
        className={cn(
          'flex items-center gap-2 border-b border-border px-4 py-3',
          collapsed && 'justify-center px-2',
        )}
      >
        <span className="grid size-7 shrink-0 place-items-center rounded-md bg-accent text-2xs font-bold text-accent-fg">
          BC
        </span>
        {collapsed ? null : (
          <span className="truncate text-sm font-semibold text-text">{t('app.name')}</span>
        )}
      </div>

      <NavList items={items} collapsed={collapsed} onNavigate={onNavigate} />

      {/* The account cluster moved to the top bar on 2026-09-14. What is
          left here is the one control that belongs to the sidebar itself. */}
      {onToggleCollapsed ? (
        <div className="border-t border-border p-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
            className={cn('w-full justify-start', collapsed && 'justify-center px-2')}
          >
            {collapsed ? (
              <ChevronsRight className="size-4 shrink-0" aria-hidden />
            ) : (
              <ChevronsLeft className="size-4 shrink-0" aria-hidden />
            )}
            {collapsed ? null : <span>{t('nav.collapse')}</span>}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function AppShell() {
  const permissions = useAuth((state) => state.permissions)
  const mustChangePassword = useAuth((state) => state.user?.must_change_password ?? false)
  const [collapsed, setCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const items = visibleNav(permissions)

  // `seed.py` and every admin reset set this flag, so the first thing a new
  // account does is choose a password only they know. Opened rather than
  // rendered inline so closing it after a successful change is one state.
  useEffect(() => {
    if (mustChangePassword) setPasswordOpen(true)
  }, [mustChangePassword])

  return (
    <div className="min-h-screen bg-bg">
      {/* Narrow screens: a top bar plus the same NAV in a drawer. */}
      <header className="flex items-center gap-3 border-b border-border bg-surface px-4 py-2 lg:hidden">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setDrawerOpen(true)}
          aria-label={t('nav.menu')}
          className="px-2"
        >
          <Menu className="size-5" aria-hidden />
        </Button>
        <span className="text-sm font-semibold text-text">{t('app.name')}</span>
        <div className="ms-auto">
          <AccountMenu />
        </div>
      </header>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label={t('common.close')}
            className="absolute inset-0 bg-text/30"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute inset-y-0 start-0 w-64">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDrawerOpen(false)}
              aria-label={t('common.close')}
              className="absolute end-2 top-2 z-10 px-2"
            >
              <X className="size-4" aria-hidden />
            </Button>
            <Sidebar
              collapsed={false}
              items={items}
              onNavigate={() => setDrawerOpen(false)}
            />
          </div>
        </div>
      ) : null}

      <div className="flex">
        <aside
          className={cn(
            'sticky top-0 hidden h-screen shrink-0 lg:block',
            collapsed ? 'w-16' : 'w-60',
          )}
        >
          <Sidebar
            collapsed={collapsed}
            onToggleCollapsed={() => setCollapsed((value) => !value)}
            items={items}
          />
        </aside>

        <main className="min-w-0 flex-1">
          {/* Top right, where every panel puts identity. Sticky, because the
              alert count is only useful if it is still there after scrolling
              a page of seven hundred calls. Hidden on narrow screens, where
              the same cluster rides in the drawer's own header instead. */}
          <header className="sticky top-0 z-20 hidden justify-end border-b border-border bg-surface px-4 py-2 lg:flex">
            <AccountMenu />
          </header>
          <Outlet />
        </main>
      </div>

      <ChangePasswordModal
        open={passwordOpen}
        onOpenChange={setPasswordOpen}
        forced={mustChangePassword}
      />
    </div>
  )
}

/** Rendered when a user reaches a URL that matches no route. */
export function NotFoundNotice() {
  return (
    <div className="flex flex-col items-center gap-2 p-10 text-center">
      <AlertTriangle className="size-8 text-warn" aria-hidden />
      <p className="text-sm font-medium text-text">{t('common.notFoundTitle')}</p>
      <p className="max-w-md text-xs text-muted">{t('common.notFoundBody')}</p>
    </div>
  )
}
