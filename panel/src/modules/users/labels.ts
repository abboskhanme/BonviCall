/**
 * Roles in Uzbek. `viewer` is gone — the TV board was the only page it could
 * see, and it went with the board — so `UserRole` is three values and this map
 * is exhaustive over the generated union.
 */
import type { MessageKey } from '@/shared/i18n'
import type { components } from '@/shared/api/types.gen'

type UserRole = components['schemas']['UserRole']

export const ROLE_LABEL: Record<UserRole, MessageKey> = {
  admin: 'role.admin',
  manager: 'role.manager',
  sales: 'role.sales',
}

/** The order the picker offers them in: least privilege first would put
 *  `sales` at the top, but `manager` is the one an admin creates most. */
export const ROLES: readonly UserRole[] = ['manager', 'sales', 'admin']

export const ROLE_TONE: Record<UserRole, 'neutral' | 'accent' | 'warn'> = {
  admin: 'warn',
  manager: 'accent',
  sales: 'neutral',
}
