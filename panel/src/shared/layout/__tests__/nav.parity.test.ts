/**
 * The two-place gate cannot drift (CONVENTIONS.md §11, SPEC §5.1).
 *
 * SPEC §5.1 asks for a test that "for each role, every route reachable through
 * the nav is also permitted by the gate". The role part belongs to the server
 * suite — the panel must not carry a role→permission map (§5.1) — so the
 * role-free half is asserted here, and it is the half that catches the mistake:
 * every permission that makes a menu entry VISIBLE must also OPEN that route's
 * gate. If it does not, some role clicks a menu item and is bounced to `/`.
 */
import { describe, expect, it } from 'vitest'

import { ROUTES } from '@/app/router'
import { NAV, visibleNav } from '@/shared/layout/AppShell'
import { messageKeys } from '@/shared/i18n'

const ROUTE_BY_PATH = new Map(ROUTES.map((route) => [route.path, route]))

describe('nav and route table', () => {
  it('points every menu entry at a registered route', () => {
    const orphans = NAV.filter((item) => !ROUTE_BY_PATH.has(item.to))
    expect(orphans.map((item) => item.to)).toEqual([])
  })

  it('never shows an entry whose gate would then refuse the user', () => {
    const mismatches: string[] = []
    for (const item of NAV) {
      const route = ROUTE_BY_PATH.get(item.to)
      if (!route?.anyOf) continue // the route lets any authenticated user in
      const gate = new Set<string>(route.anyOf)
      for (const permission of item.anyOf ?? []) {
        if (!gate.has(permission)) mismatches.push(`${item.to}: ${permission}`)
      }
      // A menu entry with no permission at all in front of a gated route would
      // show the item to everybody and bounce most of them.
      if (!item.anyOf?.length) mismatches.push(`${item.to}: nav entry has no anyOf`)
    }
    expect(mismatches).toEqual([])
  })

  it('hides every gated entry from a user with no permissions', () => {
    const visible = visibleNav(new Set<string>())
    // The dashboard, and only the dashboard. It moved to `/dashboard` on
    // 2026-09-14 when `/` became the public download page.
    expect(visible.map((item) => item.to)).toEqual(['/dashboard'])
  })

  it('offers neither the audit log nor the APK page to anybody', () => {
    // Both left the panel on 2026-09-14 at the client's request. Asserted
    // rather than remembered: a menu entry is easy to reintroduce by copying
    // a neighbouring one, and the permissions behind these two still exist.
    const everything = new Set(['audit:read', 'appversions:read', 'appversions:write'])
    const paths = visibleNav(everything).map((item) => item.to)

    expect(paths).not.toContain('/audit')
    expect(paths).not.toContain('/settings/app-versions')
  })

  it('has an Uzbek label for every menu entry', () => {
    const keys = new Set(messageKeys())
    const missing = NAV.filter((item) => !keys.has(item.labelKey)).map((item) => item.labelKey)
    expect(missing).toEqual([])
  })
})
