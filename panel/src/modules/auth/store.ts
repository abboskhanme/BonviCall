/**
 * The auth store — one of exactly two zustand stores in the panel
 * (CONVENTIONS-CLIENT.md §2: auth and theme; a third needs a line in
 * docs/ASSUMPTIONS.md).
 *
 * `can()` reads the permission list `GET /auth/me` resolved on the server. It
 * never contains a role→permission map: a second copy of that matrix is a
 * second thing to forget to update (SPEC §5.1).
 */
import { create } from 'zustand'

import { refreshAccessToken, setUnauthorizedHandler, tokenStore } from '@/shared/api/client'
import { messageForError } from '@/shared/api/errors'
import type { Permission } from '@/shared/auth/permissions'

import * as authApi from './api'
import type { SessionUser } from './api'

/**
 * `idle`   nothing tried yet — the router shows a full-page loader
 * `loading` a refresh or a login is in flight
 * `authenticated` / `anonymous` settled
 */
export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'anonymous'

interface AuthState {
  status: AuthStatus
  user: SessionUser | null
  permissions: ReadonlySet<string>
  /** The last login failure, as an Uzbek message. Cleared on the next attempt. */
  loginError: string | null
  can: (permission: Permission) => boolean
  canAny: (permissions: readonly Permission[]) => boolean
  restore: () => Promise<void>
  login: (email: string, password: string) => Promise<boolean>
  logout: () => Promise<void>
  /** Clears `must_change_password` after a successful self-change, so the
   *  forced dialog does not reappear on the next render. */
  passwordChanged: () => void
}

function settle(user: SessionUser) {
  return {
    status: 'authenticated' as const,
    user,
    permissions: new Set(user.permissions),
    loginError: null,
  }
}

const ANONYMOUS = {
  status: 'anonymous' as const,
  user: null,
  permissions: new Set<string>(),
}

export const useAuth = create<AuthState>((set, get) => ({
  status: 'idle',
  user: null,
  permissions: new Set<string>(),
  loginError: null,

  can: (permission) => get().permissions.has(permission),
  canAny: (permissions) => {
    const held = get().permissions
    return permissions.some((permission) => held.has(permission))
  },

  /**
   * Resolve the session on boot. The access token is memory-only, so after a
   * reload the HttpOnly refresh cookie is the only evidence a session exists.
   */
  restore: async () => {
    if (get().status === 'loading') return
    set({ status: 'loading' })
    const refreshed = await refreshAccessToken()
    if (!refreshed) {
      set({ ...ANONYMOUS, loginError: null })
      return
    }
    try {
      set(settle(await authApi.fetchMe()))
    } catch {
      // A valid refresh token whose user was deactivated between requests, or
      // the server restarting mid-boot. Either way there is no session.
      tokenStore.clear()
      set({ ...ANONYMOUS, loginError: null })
    }
  },

  login: async (email, password) => {
    set({ status: 'loading', loginError: null })
    try {
      await authApi.login(email, password)
      set(settle(await authApi.fetchMe()))
      return true
    } catch (error) {
      tokenStore.clear()
      set({ ...ANONYMOUS, loginError: messageForError(error) })
      return false
    }
  },

  passwordChanged: () => {
    const user = get().user
    if (user) set({ user: { ...user, must_change_password: false } })
  },

  logout: async () => {
    try {
      await authApi.logout()
    } catch {
      // The server may already have dropped the session. The local session
      // ends either way — never leave a user staring at a panel they believe
      // they have left.
    }
    tokenStore.clear()
    set({ ...ANONYMOUS, loginError: null })
  },
}))

/**
 * When a refresh fails mid-session the client clears the token and calls this.
 * Flipping the status to `anonymous` is all that is needed: the router's
 * `Protected` then redirects to /login and records where the user was, so no
 * imperative `location.assign` is required and the SPA is not reloaded.
 */
setUnauthorizedHandler(() => {
  useAuth.setState({ ...ANONYMOUS, loginError: null })
})
