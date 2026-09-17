/**
 * Faollik's place in the two lists (CONVENTIONS.md §11).
 *
 * `shared/layout/__tests__/nav.parity.test.ts` asserts the general invariant —
 * a permission that shows an entry also opens its gate — by walking both
 * lists. This file asserts the specific decision, because the general test
 * passes just as happily when the page is absent from both lists at once:
 *
 *   · it is in **Kundalik ish**, not in Tahlil — it is call statistics rather
 *     than scoring, and it is the page a call list raises the question for;
 *   · it gates on the CALL permissions, which is the only reason a salesperson
 *     can reach it at all. Gate it on an analysis or a reports permission and
 *     own-scope becomes unreachable, since `sales` holds neither.
 */
import { describe, expect, it } from 'vitest'

import { ROUTES } from '@/app/router'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { NAV, visibleNav } from '@/shared/layout/AppShell'

const CALL_PERMISSIONS = [Perm.CALLS_READ, Perm.CALLS_READ_OWN]

/** `sales`: own-scope everywhere and no analysis permission at all (§12 Q1). */
const SALES = new Set([Perm.CALLS_READ_OWN, Perm.AUDIO_PLAY_OWN, Perm.DEVICES_READ_OWN])

describe('the Faollik menu entry', () => {
  it('sits in Kundalik ish, directly after the call list', () => {
    const operations = NAV.filter((item) => item.group === 'nav.groupOperations')
    const paths = operations.map((item) => item.to)
    expect(paths.indexOf('/activity')).toBe(paths.indexOf('/calls') + 1)
  })

  it('is labelled Faollik', () => {
    const item = NAV.find((entry) => entry.to === '/activity')
    expect(item).toBeDefined()
    expect(t(item!.labelKey)).toBe('Faollik')
  })

  it('gates on the call permissions, so a salesperson keeps it', () => {
    const item = NAV.find((entry) => entry.to === '/activity')
    expect(item?.anyOf).toEqual(CALL_PERMISSIONS)
    expect(visibleNav(SALES).map((entry) => entry.to)).toContain('/activity')
  })

  it('is hidden from a user who may read no call at all', () => {
    const visible = visibleNav(new Set([Perm.USERS_READ])).map((item) => item.to)
    expect(visible).not.toContain('/activity')
  })
})

describe('the route behind it', () => {
  it('is registered with the same gate as the menu entry', () => {
    const route = ROUTES.find((entry) => entry.path === '/activity')
    expect(route, '/activity is not registered').toBeDefined()
    expect(route?.anyOf).toEqual(CALL_PERMISSIONS)
  })

  it('does not put the drill-down in the menu — it opens from a table row', () => {
    expect(NAV.map((item) => item.to)).not.toContain('/activity/:agentId')
  })
})
