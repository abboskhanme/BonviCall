/**
 * Panel accounts — TanStack Query hooks only (CONVENTIONS-CLIENT.md §1).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **A user is a login. An agent is a salesperson. Creating one never creates
 * the other** (SPEC §3.2).
 *
 * The only link is `agent_id`, and it points one way: a `sales` account names
 * exactly one agent, and an agent can exist with no account at all — most do,
 * because a salesperson needs a phone, not a password. Nothing in this module
 * registers a number or issues a code; that lives on the agent page.
 *
 * Two server guards must reach the user as sentences, not as generic
 * failures, because both are refusals to do something reasonable-looking:
 *   409 `last_admin`        — the last active admin cannot be demoted or
 *                             deactivated; a panel with no admin can only be
 *                             repaired from a shell.
 *   409 `cannot_modify_self` — you cannot deactivate or demote yourself.
 * Both already carry Uzbek text in the error catalogue.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type User = components['schemas']['UserResponse']
export type UserList = components['schemas']['UserListResponse']
export type UserRole = components['schemas']['UserRole']
export type CreateUserRequest = components['schemas']['CreateUserRequest']
export type UpdateUserRequest = components['schemas']['UpdateUserRequest']
export type SetPasswordRequest = components['schemas']['SetPasswordRequest']
export type UserQuery = NonNullable<
  operations['list_users_api_v1_users_get']['parameters']['query']
>

/** SPEC §4.7: argon2id, minimum ten characters, and no other composition
 *  rule — a rule people cannot follow is a rule they write on a sticky note. */
export const MIN_PASSWORD_LENGTH = 10

export function useUsers(params: UserQuery, enabled = true): UseQueryResult<UserList> {
  return useQuery({
    queryKey: queryKey('users', 'list', params),
    queryFn: () => api.get<UserList>('/users', { ...params }),
    // `users:read` is admin-only, so a page that merely wants a name for an
    // id must be able to ask without provoking a 403 for a manager.
    enabled,
  })
}

export function useCreateUser(): UseMutationResult<User, unknown, CreateUserRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateUserRequest) => api.post<User>('/users', body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('users') })
    },
  })
}

export function useUpdateUser(userId: string): UseMutationResult<User, unknown, UpdateUserRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateUserRequest) => api.patch<User>(`/users/${userId}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('users') })
    },
  })
}

/**
 * An admin setting somebody else's password.
 *
 * The server forces `must_change_password` and revokes every refresh token
 * that user holds, so the reset is not a way to read their session — it ends
 * it. Nothing here needs to know the old password because an admin never has
 * it: `POST /auth/password` is the self-service route and takes both.
 */
export function useSetPassword(
  userId: string,
): UseMutationResult<unknown, unknown, SetPasswordRequest> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SetPasswordRequest) => api.post(`/users/${userId}/password`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('users') })
    },
  })
}

/**
 * Would this change leave the panel with no way in?
 *
 * Checked here only so the button can be disabled with an explanation instead
 * of firing a request that comes back 409. **The server decides** — this is a
 * courtesy, and a stale roster must never be able to authorise anything.
 */
export function isLastActiveAdmin(users: User[] | undefined, user: User): boolean {
  if (user.role !== 'admin' || !user.is_active) return false
  return (users ?? []).filter((item) => item.role === 'admin' && item.is_active).length <= 1
}
