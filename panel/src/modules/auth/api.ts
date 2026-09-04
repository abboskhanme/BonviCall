/**
 * Auth calls.
 *
 * CONVENTIONS-CLIENT.md §1 says a module's `api.ts` holds TanStack Query hooks
 * only. Auth is the one exception and it is named here rather than left to be
 * discovered: the session must be resolved *before* the router renders
 * anything, so it cannot be a hook inside a component. Everything else in the
 * panel is a hook. No `fetch` appears here either — every call goes through
 * `shared/api/client.ts`.
 */
import { api, tokenStore } from '@/shared/api/client'
import type { components } from '@/shared/api/types.gen'

/** `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh`. The refresh token
 *  is an HttpOnly cookie and never appears in a body (SPEC §4.7). */
export type LoginResponse = components['schemas']['LoginResponse']

/** `GET /api/v1/auth/me` — the user plus the RESOLVED permission list.
 *  `can()` reads that list and never a role map (SPEC §5.1). */
export type SessionUser = components['schemas']['CurrentUserResponse']

/** `POST /auth/login`. Sets the access token; the refresh token arrives as an
 *  HttpOnly cookie scoped to `/api/v1/auth/refresh` (SPEC §4.7). */
export async function login(email: string, password: string): Promise<void> {
  const response = await api.postWithoutRefresh<LoginResponse>('/auth/login', {
    email,
    password,
  })
  tokenStore.set(response.access_token)
}

/** `GET /auth/me` — user, resolved permissions, must_change_password. */
export function fetchMe(): Promise<SessionUser> {
  return api.get<SessionUser>('/auth/me')
}

/** `POST /auth/logout` — revokes the refresh token server-side. */
export function logout(): Promise<void> {
  return api.postWithoutRefresh<void>('/auth/logout')
}
