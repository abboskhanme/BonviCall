/**
 * TanStack Query configuration — the panel's only server-state mechanism
 * (CONVENTIONS-CLIENT.md §2).
 *
 * **There is no WebSocket** (SPEC D-02, §5.3). Freshness comes from polling:
 * 15 s on the pages a rollout is watched through, 60 s everywhere else, with a
 * 30 s `staleTime` so a tab switch does not refetch the world.
 *
 * Query keys follow `['<module>', '<slice>', params]` and are built with
 * `queryKey()` from `shared/api/queryKeys.ts`; a mutation invalidates
 * `moduleKey('<module>')` in `onSuccess`.
 */
import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/shared/api/errors'

/** `/enrolment`, `/devices`, `/alerts` — a rollout is watched live. */
export const POLL_FAST_MS = 15_000

/** Everywhere else. */
export const POLL_DEFAULT_MS = 60_000

export const STALE_TIME_MS = 30_000

/**
 * Retrying a 4xx is pointless and, on a 403, it is three identical audit rows.
 * A 401 is already handled inside the client, which refreshes once and replays.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 2
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_TIME_MS,
        refetchInterval: POLL_DEFAULT_MS,
        refetchOnWindowFocus: true,
        retry: shouldRetry,
      },
      mutations: { retry: false },
    },
  })
}
