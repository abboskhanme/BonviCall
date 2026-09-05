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
  AlertTriangle,
  BellRing,
  ChevronsLeft,
  ChevronsRight,
  FileWarning,
  HardDrive,
  LayoutDashboard,
  KeyRound,
  LogOut,
  Menu,
  MonitorPlay,
  Moon,
  Package,
  Phone,
  ScrollText,
  Settings,
  Smartphone,
  SunMedium,
  UserCog,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { ChangePasswordModal } from '@/modules/auth/ChangePasswordModal'
import { useAuth } from '@/modules/auth/store'
import { Perm, type Permission } from '@/shared/auth/permissions'
import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { useTheme, type Theme } from '@/shared/theme/store'
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
  { to: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard },

  {
    to: '/calls',
    labelKey: 'nav.calls',
    icon: Phone,
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
    // Own-scope is here on purpose: a salesperson holding `devices:read:own`
    // gets a one-row list — their own phone's health, "is it still
    // reporting?" — because the SERVER narrows the query, not the permission
    // (CONVENTIONS.md §11). Same shape as their calls page.
    to: '/devices',
    labelKey: 'nav.devices',
    icon: Smartphone,
    anyOf: [Perm.DEVICES_READ, Perm.DEVICES_READ_OWN],
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
    to: '/reports/gap',
    labelKey: 'nav.gapReport',
    icon: FileWarning,
    anyOf: [Perm.REPORTS_READ],
    group: 'nav.groupReports',
  },
  {
    to: '/reports/storage',
    labelKey: 'nav.storageReport',
    icon: HardDrive,
    anyOf: [Perm.REPORTS_READ],
    group: 'nav.groupReports',
  },

  {
    to: '/users',
    labelKey: 'nav.users',
    icon: UserCog,
    anyOf: [Perm.USERS_READ],
    group: 'nav.groupAdmin',
  },
  {
    to: '/settings',
    labelKey: 'nav.settings',
    icon: Settings,
    anyOf: [Perm.SETTINGS_READ],
    group: 'nav.groupAdmin',
  },
  {
    to: '/settings/app-versions',
    labelKey: 'nav.appVersions',
    icon: Package,
    anyOf: [Perm.APPVERSIONS_READ],
    group: 'nav.groupAdmin',
  },
  {
    to: '/audit',
    labelKey: 'nav.audit',
    icon: ScrollText,
    anyOf: [Perm.AUDIT_READ],
    group: 'nav.groupAdmin',
  },
]

/** The items this permission set may see. Pure, so the parity test can use it. */
export function visibleNav(
  held: ReadonlySet<string>,
  nav: readonly NavItem[] = NAV,
): NavItem[] {
  return nav.filter((item) => !item.anyOf || item.anyOf.some((perm) => held.has(perm)))
}

const THEME_ORDER: readonly Theme[] = ['system', 'light', 'dark']
const THEME_ICON: Record<Theme, IconComponent> = {
  system: MonitorPlay,
  light: SunMedium,
  dark: Moon,
}
const THEME_LABEL: Record<Theme, MessageKey> = {
  system: 'theme.system',
  light: 'theme.light',
  dark: 'theme.dark',
}

function ThemeToggle({ collapsed }: { collapsed: boolean }) {
  const { theme, setTheme } = useTheme()
  const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length] ?? 'system'
  const Icon = THEME_ICON[theme]
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(next)}
      title={t('theme.label')}
      aria-label={t(THEME_LABEL[theme])}
      className={cn('w-full justify-start', collapsed && 'justify-center px-2')}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {collapsed ? null : <span className="truncate">{t(THEME_LABEL[theme])}</span>}
    </Button>
  )
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
              end={item.to === '/' || item.to === '/settings'}
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
  onChangePassword,
}: {
  collapsed: boolean
  onToggleCollapsed?: () => void
  items: readonly NavItem[]
  onNavigate?: () => void
  onChangePassword: () => void
}) {
  const { user, logout } = useAuth()
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

      <div className="space-y-1 border-t border-border p-2">
        <ThemeToggle collapsed={collapsed} />
        {collapsed ? null : user ? (
          <div className="px-3 py-1">
            <p className="truncate text-xs font-medium text-text">{user.full_name}</p>
            <p className="truncate text-2xs text-muted">{user.email}</p>
          </div>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          onClick={onChangePassword}
          className={cn('w-full justify-start', collapsed && 'justify-center px-2')}
          aria-label={t('password.title')}
        >
          <KeyRound className="size-4 shrink-0" aria-hidden />
          {collapsed ? null : <span className="truncate">{t('password.title')}</span>}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void logout()}
          className={cn('w-full justify-start', collapsed && 'justify-center px-2')}
          aria-label={t('auth.logout')}
        >
          <LogOut className="size-4 shrink-0" aria-hidden />
          {collapsed ? null : <span>{t('auth.logout')}</span>}
        </Button>
        {onToggleCollapsed ? (
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
        ) : null}
      </div>
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
              onChangePassword={() => {
                setDrawerOpen(false)
                setPasswordOpen(true)
              }}
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
            onChangePassword={() => setPasswordOpen(true)}
          />
        </aside>

        <main className="min-w-0 flex-1">
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
